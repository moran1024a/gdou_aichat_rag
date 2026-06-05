from django.urls import path

from .views import (
    chat,
    chat_view,
    console_activate_database,
    console_create_database,
    console_dashboard,
    console_delete_database,
    console_login,
    console_login_submit,
    console_logout,
    console_update_runtime_config,
    console_upload_document,
)

urlpatterns = [
    path('chat_view', chat_view),
    path('chat', chat),
    path('console/login', console_login),
    path('console/login/submit', console_login_submit),
    path('console/logout', console_logout),
    path('console/', console_dashboard),
    path('console/databases/create', console_create_database),
    path('console/databases/<int:db_id>/upload', console_upload_document),
    path('console/databases/<int:db_id>/activate', console_activate_database),
    path('console/databases/<int:db_id>/delete', console_delete_database),
    path('console/settings', console_update_runtime_config),
]
