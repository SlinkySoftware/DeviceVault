
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from api import views

router = routers.DefaultRouter()
router.register(r'device-types', views.DeviceTypeViewSet)
router.register(r'manufacturers', views.ManufacturerViewSet)
router.register(r'devices', views.DeviceViewSet)
router.register(r'backups', views.BackupViewSet)
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

urlpatterns = [
    path('admin/', admin.site.urls), 
    path('api/', include(router.urls)), 
    path('api/onboarding/', views.onboarding), 
    path('api/dashboard-stats/', views.dashboard_stats),
    path('api/auth/config/', views.AuthConfigView.as_view()), 
    path('api/backups/compare/', views.compare_backups),
    path('api/auth/login/', views.LoginView.as_view()), 
    path('api/auth/logout/', views.LogoutView.as_view()), 
    path('api/auth/user/', views.UserInfoView.as_view()),
    path('api/auth/change-password/', views.ChangePasswordView.as_view()),
    path('api/dashboard-layout/', views.DashboardLayoutView.as_view()),
    path('api/dashboard-layout/default/', views.DashboardDefaultLayoutView.as_view()),
    path('api/user/preferences/', views.UserPreferencesView.as_view()),
]
