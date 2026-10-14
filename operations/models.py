from django.db import models


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=64, primary_key=True)
    last_seen = models.DateTimeField()
