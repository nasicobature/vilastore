from django.shortcuts import redirect, render

from .tenant import institution_from_host, subdomain_from_host


class EduTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.edu_subdomain = subdomain_from_host(request.get_host())
        request.edu_institution = institution_from_host(request.get_host()) if request.edu_subdomain else None
        if request.edu_subdomain and not self._is_shared_asset_or_health_path(request.path):
            if not request.edu_institution:
                return render(request, 'edu/portal_not_found.html', status=404)
            if request.path not in {'/', '/dashboard/'} and not request.path.startswith('/edu/'):
                return redirect('/')
        return self.get_response(request)

    @staticmethod
    def _is_shared_asset_or_health_path(path):
        return (
            path.startswith('/static/')
            or path.startswith('/media/')
            or path in {'/healthz/', '/service-worker.js', '/favicon.ico'}
        )
