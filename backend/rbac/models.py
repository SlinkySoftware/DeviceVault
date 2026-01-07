"""
Role-Based Access Control Models
Contains group label assignments for tag-based access control.
Device Group RBAC has been moved to devices app.
"""

from django.db import models
from django.contrib.auth.models import Group as AuthGroup
from core.models import Label


class GroupLabelAssignment(models.Model):
    """
    Maps Django auth Group to Label (for tag-based device filtering)
    """
    group = models.ForeignKey(AuthGroup, on_delete=models.CASCADE, related_name='label_assignments')
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name='group_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True, help_text='When the label was assigned to the group')

    class Meta:
        unique_together = ('group', 'label')
        verbose_name = 'Group Label Assignment'
        verbose_name_plural = 'Group Label Assignments'

    def __str__(self):
        return f"{self.group.name} -> {self.label.name}"
