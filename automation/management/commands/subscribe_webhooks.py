from django.core.management.base import BaseCommand
from automation.integrations import WazzUp


class Command(BaseCommand):
    help = "Подписаться на вебхуки WazzUp24"

    def add_arguments(self, parser):
        parser.add_argument("url", help="Публичный URL вебхука, например https://yourdomain.com/webhooks/wazzup/")

    def handle(self, *args, **options):
        url = options["url"]
        self.stdout.write(f"Подписываемся на вебхуки WazzUp: {url}")
        WazzUp().subscribe_webhooks(url)
        self.stdout.write(self.style.SUCCESS("Готово! WazzUp будет слать события на этот URL."))
