class EduTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.edu_subdomain = ''
        request.edu_institution = None
        return self.get_response(request)
