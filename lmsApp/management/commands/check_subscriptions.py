from django.core.management.base import BaseCommand
from django.utils import timezone
from lmsApp.models import Team

class Command(BaseCommand):
    help = 'Checks for expired team subscriptions and deactivates them and their members.'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Find all active teams whose subscription end date is in the past.
        expired_teams = Team.objects.filter(is_active=True, subscription_ends__lt=now)
        
        if expired_teams.exists():
            deactivated_team_count = expired_teams.count()
            deactivated_user_count = 0
            
            self.stdout.write(f"Found {deactivated_team_count} expired team subscriptions...")

            for team in expired_teams:
                # 1. Deactivate the team itself
                team.is_active = False
                team.save()
                self.stdout.write(f"  - Deactivated team: {team.name}")

                # 2. Deactivate all members of the expired team, but NOT the owner
                for member in team.members.all():
                    # The owner is linked via a OneToOneField 'owned_team'. 
                    # We check if the member is also an owner of any team.
                    # This safely skips the owner of this team.
                    if not hasattr(member, 'owned_team'):
                        member.is_active = False
                        member.is_b2b_member = False # Revoke their B2B status
                        member.save()
                        deactivated_user_count += 1
                        self.stdout.write(f"    - Deactivated member: {member.email}")
            
            self.stdout.write(self.style.SUCCESS(f'\nSuccessfully deactivated {deactivated_team_count} teams and {deactivated_user_count} members.'))
        else:
            self.stdout.write(self.style.NOTICE('No expired subscriptions found.'))

