-- RBAC (Role-Based Access Control) schema

-- Roles
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Permissions
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) UNIQUE NOT NULL,
    resource VARCHAR(100) NOT NULL, -- e.g., 'users', 'posts'
    action VARCHAR(50) NOT NULL,    -- e.g., 'create', 'read', 'update', 'delete'
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Role-Permission junction
CREATE TABLE role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role_id, permission_id)
);

-- User-Role junction
CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    assigned_by UUID REFERENCES users(id),
    PRIMARY KEY (user_id, role_id)
);

-- Indexes
CREATE INDEX idx_role_permissions_role ON role_permissions(role_id);
CREATE INDEX idx_role_permissions_permission ON role_permissions(permission_id);
CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);

-- Default roles
INSERT INTO roles (name, description) VALUES
    ('admin', 'Full system access'),
    ('user', 'Standard user access'),
    ('guest', 'Read-only access');

-- Default permissions
INSERT INTO permissions (name, resource, action, description) VALUES
    ('users.create', 'users', 'create', 'Create new users'),
    ('users.read', 'users', 'read', 'Read user data'),
    ('users.update', 'users', 'update', 'Update user data'),
    ('users.delete', 'users', 'delete', 'Delete users'),
    ('posts.create', 'posts', 'create', 'Create posts'),
    ('posts.read', 'posts', 'read', 'Read posts'),
    ('posts.update', 'posts', 'update', 'Update posts'),
    ('posts.delete', 'posts', 'delete', 'Delete posts');

-- Grant all permissions to admin role
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = 'admin';
