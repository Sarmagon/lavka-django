from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from .models import Order


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CheckoutView(TemplateView):
    template_name = "frontend/order.html"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CustomerView(LoginRequiredMixin, TemplateView):
    login_url = "/sign-in/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = kwargs.get("id")
        if pk is None and self.template_name in ("frontend/paymentsomeone.html", "frontend/progressPayment.html"):
            pk = self.request.GET.get("order")
        if pk is not None:
            try:
                pk = int(pk)
            except (TypeError, ValueError):
                pk = 0
            get_object_or_404(Order.objects.alive(), pk=pk, user=self.request.user)
        elif self.template_name in ("frontend/paymentsomeone.html", "frontend/progressPayment.html"):
            get_object_or_404(Order.objects.none())
        return context
