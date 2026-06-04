from django.urls import path

from .views import chat_view, upload_view, chat, upload

urlpatterns = [
    path('chat_view', chat_view),
    path('upload_view', upload_view),
    path('chat', chat),
    path('upload', upload)
]