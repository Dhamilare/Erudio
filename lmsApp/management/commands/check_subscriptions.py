from django.core.management.base import BaseCommand
from django.utils import timezone
from lmsApp.models import Team

class Command(BaseCommand):
    help = 'Checks for expired team subscriptions and deactivates them.'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Find all active teams whose subscription end date is in the past.
        expired_teams = Team.objects.filter(is_active=True, subscription_ends__lt=now)
        
        if expired_teams.exists():
            count = expired_teams.count()
            
            # Deactivate each expired team.
            for team in expired_teams:
                team.is_active = False
                team.save()
                
            self.stdout.write(self.style.SUCCESS(f'Successfully deactivated {count} expired team subscriptions.'))
        else:
            self.stdout.write(self.style.NOTICE('No expired subscriptions found.'))
