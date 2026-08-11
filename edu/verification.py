import os

import requests
from django.conf import settings
from django.utils import timezone

from .models import InstitutionDocumentVerification


DOCUMENT_FIELDS = [
    'cac_certificate',
    'cac_status_report',
    'ministry_approval',
    'operating_license',
    'tin_certificate',
    'school_letterhead',
    'school_stamp',
    'owner_valid_id',
    'utility_bill',
    'proof_of_address',
]

API_DOCUMENT_TYPES = {
    'cac_certificate': 'cac',
    'cac_status_report': 'cac',
    'tin_certificate': 'tin',
    'owner_valid_id': 'nin',
}


def _verification_api_config(api_kind):
    configured = getattr(settings, 'EDU_VERIFICATION_APIS', {})
    if configured.get(api_kind):
        return configured[api_kind]

    prefix = f'EDU_{api_kind.upper()}_VERIFICATION'
    return {
        'url': getattr(settings, f'{prefix}_URL', '') or os.environ.get(f'{prefix}_URL', ''),
        'token': getattr(settings, f'{prefix}_TOKEN', '') or os.environ.get(f'{prefix}_TOKEN', ''),
        'provider': getattr(settings, f'{prefix}_PROVIDER', '') or os.environ.get(f'{prefix}_PROVIDER', api_kind.upper()),
    }


def _reference_for_document(institution, document_type):
    if document_type in {'cac_certificate', 'cac_status_report'}:
        return institution.cac_number
    if document_type == 'tin_certificate':
        return institution.tin_number
    if document_type == 'owner_valid_id':
        return institution.owner_id_number
    return ''


def _api_verified(payload):
    status = str(payload.get('status', '')).lower()
    return bool(
        payload.get('verified') is True
        or payload.get('valid') is True
        or status in {'verified', 'valid', 'success', 'approved'}
    )


def verify_document_with_api(document):
    api_kind = API_DOCUMENT_TYPES.get(document.document_type)
    if not api_kind:
        document.status = 'manual_review'
        document.provider = 'Manual Review'
        document.api_response = {'detail': 'No automatic API is required for this document type.'}
        document.api_checked_at = timezone.now()
        document.save(update_fields=['status', 'provider', 'api_response', 'api_checked_at', 'updated_at'])
        return document

    config = _verification_api_config(api_kind)
    url = config.get('url')
    token = config.get('token', '')
    provider = config.get('provider') or api_kind.upper()

    if not url:
        document.status = 'manual_review'
        document.provider = provider
        document.api_response = {'detail': f'{provider} API is not configured yet.'}
        document.api_checked_at = timezone.now()
        document.save(update_fields=['status', 'provider', 'api_response', 'api_checked_at', 'updated_at'])
        return document

    payload = {
        'document_type': document.document_type,
        'reference': document.reference_value,
        'institution_name': document.institution.name,
        'school_code': document.institution.school_code,
    }
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response_data = response.json() if response.content else {}
        document.status = 'api_verified' if response.ok and _api_verified(response_data) else 'api_failed'
        document.api_response = response_data or {'status_code': response.status_code}
    except requests.RequestException as exc:
        document.status = 'api_failed'
        document.api_response = {'error': str(exc)}

    document.provider = provider
    document.api_checked_at = timezone.now()
    document.save(update_fields=['status', 'provider', 'api_response', 'api_checked_at', 'updated_at'])
    return document


def create_document_verifications(institution, run_api=True):
    documents = []
    for field_name in DOCUMENT_FIELDS:
        file_value = getattr(institution, field_name, None)
        if not file_value:
            continue

        document, _ = InstitutionDocumentVerification.objects.update_or_create(
            institution=institution,
            document_type=field_name,
            defaults={
                'document_file': file_value.name,
                'reference_value': _reference_for_document(institution, field_name),
                'status': 'pending',
            },
        )
        if run_api:
            document = verify_document_with_api(document)
        documents.append(document)
    return documents
