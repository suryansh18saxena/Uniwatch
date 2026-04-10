from django import forms
from .models import Server


class AddServerForm(forms.ModelForm):
    """
    Form for adding a new server to monitor.
    SSH private key is collected but NOT stored in the database.
    """

    ssh_private_key = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 8,
            'placeholder': '-----BEGIN RSA PRIVATE KEY-----\nPaste your full private key here...\n-----END RSA PRIVATE KEY-----',
            'class': 'form-input',
            'id': 'id_ssh_private_key',
        }),
        help_text="Your SSH private key (PEM format). Used once for setup, then immediately deleted.",
        label="SSH Private Key"
    )

    class Meta:
        model = Server
        fields = ['name', 'ip_address', 'ssh_user', 'has_containers']
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'e.g., Production-Server-1',
                'class': 'form-input',
                'id': 'id_name',
            }),
            'ip_address': forms.TextInput(attrs={
                'placeholder': 'e.g., 54.123.45.67',
                'class': 'form-input',
                'id': 'id_ip_address',
            }),
            'ssh_user': forms.TextInput(attrs={
                'placeholder': 'e.g., ubuntu, ec2-user',
                'class': 'form-input',
                'id': 'id_ssh_user',
            }),
            'has_containers': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
                'id': 'id_has_containers',
            }),
        }
