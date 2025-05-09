from django.urls import path
from .views import CreateRequestView, GetRequestStatusView

urlpatterns = [
    path('requests/', CreateRequestView.as_view()),
    path('requests/<str:request_id>/', GetRequestStatusView.as_view()),
]
