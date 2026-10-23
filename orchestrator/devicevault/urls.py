"""
DeviceVault URL configuration module

Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from api import views
from backups import api as backup_api

router = routers.DefaultRouter()
router.register(r'device-types', views.DeviceTypeViewSet)
router.register(r'manufacturers', views.ManufacturerViewSet)
router.register(r'collection-groups', views.CollectionGroupViewSet)
router.register(r'backup-methods', views.BackupMethodViewSet, basename='backup-methods')
router.register(r'devices', views.DeviceViewSet)
router.register(r'backups', backup_api.BackupJobViewSet, basename='backups')
router.register(r'retention-policies', views.RetentionPolicyViewSet)
router.register(r'backup-schedules', views.BackupScheduleViewSet)
router.register(r'backup-locations', views.BackupLocationViewSet)
router.register(r'credentials', views.CredentialViewSet)
router.register(r'credential-types', views.CredentialTypeViewSet)
router.register(r'groups', views.GroupViewSet)
router.register(r'device-groups', views.DeviceGroupViewSet)
router.register(r'device-group-roles', views.DeviceGroupRoleViewSet)
router.register(r'device-group-permissions', views.DeviceGroupPermissionViewSet)
router.register(r'user-device-group-roles', views.UserDeviceGroupRoleViewSet)
router.register(r'group-device-group-roles', views.GroupDeviceGroupRoleViewSet)
router.register(r'users', views.UserViewSet, basename='users')
router.register(r'audit-logs', views.AuditLogViewSet)
router.register(r'workers', views.WorkerViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/health/', views.health),
    path('api/onboarding/', views.onboarding),
    path('api/dashboard-stats/', backup_api.dashboard_stats),
    path('api/recent-backup-activity/', backup_api.recent_backup_activity),
    path('api/timezone/', views.timezone_config),
    path('api/auth/config/', views.AuthConfigView.as_view()),
    path('api/auth/login/', views.LoginView.as_view()),
    path('api/auth/logout/', views.LogoutView.as_view()),
    path('api/auth/user/', views.UserInfoView.as_view()),
    path('api/auth/change-password/', views.ChangePasswordView.as_view()),
    path('api/theme-settings/', views.ThemeSettingsView.as_view()),
    path('api/user/preferences/', views.UserPreferencesView.as_view()),
    # Dashboard layout/customization disabled; fixed layout only
]
