import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Server
from .utils import setup_server_with_ansible

@csrf_exempt  # CSRF disable kar rahe hain taaki Postman/cURL se easily test kar sakein
def add_server(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name', 'Unnamed Server')
            ip_address = data.get('ip_address')
            ssh_user = data.get('ssh_user', 'ubuntu')

            if not ip_address:
                return JsonResponse({"error": "IP Address is required"}, status=400)

            # 1. Server ko Database mein save karo (ya pehle se hai toh get karo)
            server, created = Server.objects.get_or_create(
                ip_address=ip_address,
                defaults={'name': name, 'ssh_user': ssh_user}
            )

            # 2. Ansible Playbook Trigger karo
            # (Note: Yeh process thoda time legi kyunki Ansible remote machine setup kar raha hai)
            success, logs = setup_server_with_ansible(ip_address, ssh_user)

            if success:
                server.is_active = True
                server.save()
                return JsonResponse({
                    "status": "success", 
                    "message": "Node Exporter successfully installed and running!", 
                    "logs": logs
                })
            else:
                return JsonResponse({
                    "status": "error", 
                    "message": "Ansible setup failed", 
                    "logs": logs
                }, status=500)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)