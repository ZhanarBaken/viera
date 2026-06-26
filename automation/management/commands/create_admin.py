import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create superuser from env vars if not exists"

    def handle(self, *args, **kwargs):
        User = get_user_model()
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "")
        email = os.environ.get("ADMIN_EMAIL", "")

        if not password:
            self.stdout.write("ADMIN_PASSWORD not set, skipping superuser creation")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Superuser '{username}' already exists")
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(f"Superuser '{username}' created")
