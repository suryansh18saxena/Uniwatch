from django.contrib import admin
from django.urls import path, include  # include ko import karna mat bhoolna

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('monitor.urls')),  # Ab humari API '/api/add-server/' par available hogi
]