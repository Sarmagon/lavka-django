from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView


@method_decorator(login_required(login_url="/sign-in/"), name="dispatch")
class ProfileView(TemplateView):
    template_name = "frontend/profile.html"
