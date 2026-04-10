from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('add-server/', views.add_server, name='add_server'),
    path('server/<int:server_id>/', views.server_detail, name='server_detail'),
    path('server/<int:server_id>/delete/', views.delete_server, name='delete_server'),
    path('server/<int:server_id>/retry/', views.retry_setup, name='retry_setup'),
]