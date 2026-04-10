from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('add-server/', views.add_server, name='add_server'),
    path('server/<int:server_id>/', views.server_detail, name='server_detail'),
    path('server/<int:server_id>/delete/', views.delete_server, name='delete_server'),
    path('server/<int:server_id>/retry/', views.retry_setup, name='retry_setup'),

    # Alert system
    path('alerts/', views.alerts_list, name='alerts_list'),
    path('alerts/<int:alert_id>/', views.alert_detail, name='alert_detail'),
    path('alerts/<int:alert_id>/fix/', views.execute_fix, name='execute_fix'),
    path('alerts/<int:alert_id>/dismiss/', views.dismiss_alert, name='dismiss_alert'),
    path('alerts/check/', views.check_alerts, name='check_alerts'),
]