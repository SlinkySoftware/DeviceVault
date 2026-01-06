from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = 'Create a default admin user if it does not exist'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin', help='Admin username')
        parser.add_argument('--password', type=str, default='admin123', help='Admin password')
        parser.add_argument('--email', type=str, default='admin@devicevault.local', help='Admin email')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        email = options['email']

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User {username} already exists'))
        else:
            user = User.objects.create_superuser(username, email, password)
            Token.objects.get_or_create(user=user)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created admin user "{username}" with password "{password}"')
            )
