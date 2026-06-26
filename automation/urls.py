from django.urls import path
from . import views

urlpatterns = [
    path("wazzup/", views.wazzup_webhook),
    path("amocrm/", views.amocrm_webhook),
]
