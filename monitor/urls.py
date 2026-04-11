from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing'),

    path('add-server/', views.add_server, name='add_server'),
    path('server/<int:server_id>/', views.server_detail, name='server_detail'),
    path('server/<int:server_id>/api/timeseries/', views.server_timeseries_api, name='server_timeseries_api'),
    path('server/<int:server_id>/delete/', views.delete_server, name='delete_server'),
    path('server/<int:server_id>/retry/', views.retry_setup, name='retry_setup'),

    # Self-Healing API
    path('server/<int:server_id>/api/fix/<str:metric_name>/preview/', views.api_fix_preview, name='api_fix_preview'),
    path('server/<int:server_id>/api/fix/<str:metric_name>/execute/', views.api_fix_execute, name='api_fix_execute'),
    path('server/<int:server_id>/api/fix/history/', views.api_fix_history, name='api_fix_history'),
    path('server/<int:server_id>/api/autofix/toggle/', views.api_toggle_autofix, name='api_toggle_autofix'),
]