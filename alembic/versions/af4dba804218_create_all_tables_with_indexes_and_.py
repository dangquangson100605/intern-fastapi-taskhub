"""create all tables with indexes and server defaults

Revision ID: af4dba804218
Revises:
Create Date: 2026-11-07 16:24:46.986606

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'af4dba804218'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('ADMIN', 'MEMBER', name='userrole', native_enum=False, create_constraint=True), server_default='MEMBER', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('workspaces',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workspaces_owner_id'), 'workspaces', ['owner_id'], unique=False)
    op.create_table('projects',
    sa.Column('workspace_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('ACTIVE', 'ARCHIVED', name='projectstatus', native_enum=False, create_constraint=True), server_default='ACTIVE', nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_workspace_id'), 'projects', ['workspace_id'], unique=False)
    op.create_table('workspace_members',
    sa.Column('workspace_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('OWNER', 'EDITOR', 'VIEWER', name='workspacerole', native_enum=False, create_constraint=True), server_default='VIEWER', nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_user')
    )
    op.create_index(op.f('ix_workspace_members_user_id'), 'workspace_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_workspace_members_workspace_id'), 'workspace_members', ['workspace_id'], unique=False)
    op.create_table('labels',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=7), server_default='#3B82F6', nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_labels_project_id'), 'labels', ['project_id'], unique=False)
    op.create_table('tasks',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('TODO', 'IN_PROGRESS', 'IN_REVIEW', 'DONE', name='taskstatus', native_enum=False, create_constraint=True), server_default='TODO', nullable=False),
    sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'URGENT', name='taskpriority', native_enum=False, create_constraint=True), server_default='MEDIUM', nullable=False),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_assignee_id'), 'tasks', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_tasks_created_by'), 'tasks', ['created_by'], unique=False)
    op.create_index(op.f('ix_tasks_project_id'), 'tasks', ['project_id'], unique=False)
    op.create_table('comments',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('UTC_TIMESTAMP()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comments_author_id'), 'comments', ['author_id'], unique=False)
    op.create_index(op.f('ix_comments_task_id'), 'comments', ['task_id'], unique=False)
    op.create_table('task_labels',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('label_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['label_id'], ['labels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'label_id')
    )
    op.create_index(op.f('ix_task_labels_label_id'), 'task_labels', ['label_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_labels_label_id'), table_name='task_labels')
    op.drop_table('task_labels')
    op.drop_index(op.f('ix_comments_task_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_author_id'), table_name='comments')
    op.drop_table('comments')
    op.drop_index(op.f('ix_tasks_project_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_created_by'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_assignee_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_labels_project_id'), table_name='labels')
    op.drop_table('labels')
    op.drop_index(op.f('ix_workspace_members_workspace_id'), table_name='workspace_members')
    op.drop_index(op.f('ix_workspace_members_user_id'), table_name='workspace_members')
    op.drop_table('workspace_members')
    op.drop_index(op.f('ix_projects_workspace_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_workspaces_owner_id'), table_name='workspaces')
    op.drop_table('workspaces')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
