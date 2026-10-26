"""Write the generated Zabbix template file (monitoring.zabbix) for one Zabbix version."""

from pathlib import Path

from django.core.management.base import BaseCommand

from monitoring import zabbix


class Command(BaseCommand):
    help = 'Write the DeviceVault Zabbix templates for Zabbix 6.0 or 7.0 (to stdout, or --output)'

    def create_parser(self, prog_name, subcommand, **kwargs):
        # --version names the Zabbix version here, replacing Django's own --version.
        return super().create_parser(prog_name, subcommand, conflict_handler='resolve', **kwargs)

    def add_arguments(self, parser):
        parser.add_argument('--version', required=True, choices=zabbix.VERSIONS, help='Zabbix version')
        parser.add_argument('--output', help='Write to this file instead of stdout')

    def handle(self, *args, version, output=None, **options):
        content = zabbix.render(version)
        if output:
            Path(output).write_text(content)
            self.stderr.write(f'Wrote the Zabbix {version} templates to {output}')
        else:
            self.stdout.write(content, ending='')
