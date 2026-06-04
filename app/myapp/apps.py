from django.apps import AppConfig
from .rag import SchoolRAG

class MyappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'

    def ready(self):
        SchoolRAG()
