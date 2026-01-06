
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
router.register(r'backup-locations', views.BackupLocationViewSet)
router.register(r'credentials', views.CredentialViewSet)
router.register(r'credential-types', views.CredentialTypeViewSet)
router.register(r'labels', views.LabelViewSet)
router.register(r'roles', views.RoleViewSet)
router.register(r'permissions', views.PermissionViewSet)
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
    path('api/auth/change-password/', views.ChangePasswordView.as_view())
]
