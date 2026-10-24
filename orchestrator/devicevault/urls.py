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

from django.urls import include, path
from rest_framework import routers

from accounts import api as accounts_api
from accounts import oidc_views, provider_api
from api import views
from audit import api as audit_api
from backups import api as backup_api
from monitoring import api as monitoring_api
from storage import api as storage_api

router = routers.DefaultRouter()
router.register(r'device-types', views.DeviceTypeViewSet)
router.register(r'manufacturers', views.ManufacturerViewSet)
router.register(r'collection-groups', views.CollectionGroupViewSet)
router.register(r'backup-methods', views.BackupMethodViewSet, basename='backup-methods')
router.register(r'devices', views.DeviceViewSet, basename='devices')
router.register(r'backups', backup_api.BackupJobViewSet, basename='backups')
router.register(r'retention-policies', views.RetentionPolicyViewSet)
router.register(r'backup-schedules', views.BackupScheduleViewSet)
router.register(r'storage-targets', storage_api.StorageTargetViewSet, basename='storage-targets')
router.register(r'storage-drivers', storage_api.StorageDriverViewSet, basename='storage-drivers')
router.register(r'credentials', views.CredentialViewSet, basename='credentials')
router.register(r'credential-types', views.CredentialTypeViewSet)
router.register(r'device-groups', views.DeviceGroupViewSet, basename='device-groups')
router.register(r'users', accounts_api.UserViewSet, basename='users')
router.register(r'user-groups', accounts_api.UserGroupViewSet, basename='user-groups')
router.register(r'auth-providers', provider_api.AuthProviderViewSet, basename='auth-providers')
router.register(r'auth-provider-kinds', provider_api.AuthProviderKindViewSet, basename='auth-provider-kinds')
router.register(r'audit-logs', audit_api.AuditLogViewSet, basename='audit-logs')
router.register(r'workers', views.WorkerViewSet)
router.register(r'flower-endpoints', monitoring_api.FlowerEndpointViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('api/health/', views.health),
    path('api/flower-auth/', monitoring_api.flower_auth),
    path('api/onboarding/', views.onboarding),
    path('api/dashboard-stats/', backup_api.dashboard_stats),
    path('api/recent-backup-activity/', backup_api.recent_backup_activity),
    path('api/timezone/', views.timezone_config),
    path('api/auth/config/', accounts_api.AuthConfigView.as_view()),
    path('api/auth/csrf/', accounts_api.CsrfView.as_view()),
    path('api/auth/login/', accounts_api.LoginView.as_view()),
    path('api/auth/logout/', accounts_api.LogoutView.as_view()),
    path('api/auth/oidc/<slug:slug>/login/', oidc_views.OidcLoginView.as_view()),
    path('api/auth/oidc/<slug:slug>/callback/', oidc_views.OidcCallbackView.as_view()),
    path('api/auth/user/', accounts_api.CurrentUserView.as_view()),
    path('api/auth/change-password/', accounts_api.ChangePasswordView.as_view()),
    path('api/user/preferences/', views.UserPreferencesView.as_view()),
]
