from django.core.management.base import BaseCommand, CommandError
from myapp.models import RagDatabase
from myapp.rag import rag_manager

class Command(BaseCommand):
    help = '重建指定知识库的 TXT 索引（执行前请停服）'
    def add_arguments(self, parser): parser.add_argument('database_id', type=int)
    def handle(self, *args, **opts):
        db=RagDatabase.objects.get(pk=opts['database_id']); db.index_status='rebuilding'; db.save(update_fields=['index_status','updated_at'])
        try:
            rag_manager.invalidate(db.id); rag_manager.get_rag(db); db.index_status='ready'; db.save(update_fields=['index_status','updated_at']); self.stdout.write(self.style.SUCCESS('索引已重建'))
        except Exception as exc:
            db.index_status='failed'; db.save(update_fields=['index_status','updated_at']); raise CommandError(str(exc))
