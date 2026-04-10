from django.urls import path
from . import views

urlpatterns = [
    path('add-server/', views.add_server, name='add_server'),
]