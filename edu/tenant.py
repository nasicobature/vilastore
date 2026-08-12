from django.conf import settings

from .models import Institution, RESERVED_EDU_SUBDOMAINS


def edu_root_domain():
    return getattr(settings, 'EDU_ROOT_DOMAIN', 'vilastore.store').strip().lower()


def subdomain_from_host(host):
    host = (host or '').split(':', 1)[0].lower()
    root_domain = edu_root_domain()
    if not host.endswith('.' + root_domain):
        return ''
    subdomain = host[:-(len(root_domain) + 1)].strip('.')
    if not subdomain or subdomain in RESERVED_EDU_SUBDOMAINS:
        return ''
    return Institution.normalize_subdomain(subdomain)


def institution_from_host(host):
    subdomain = subdomain_from_host(host)
    if not subdomain:
        return None
    return Institution.objects.filter(school_code__iexact=subdomain).first()
