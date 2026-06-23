import { Layout as AntLayout, Menu, Avatar, Dropdown, Space, Button, Modal, Descriptions, Tag } from 'antd';
import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  DashboardOutlined, ProjectOutlined, LogoutOutlined, UserOutlined,
  DatabaseOutlined, AppstoreOutlined, TeamOutlined, ApartmentOutlined,
  CloudUploadOutlined, ThunderboltOutlined, ExperimentOutlined, ApiOutlined, CloudServerOutlined, EyeOutlined
} from '@ant-design/icons';
import { useI18n } from '../i18n';

const { Header, Sider, Content } = AntLayout;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { lang, t, setLang } = useI18n();

  const [profileOpen, setProfileOpen] = useState(false);
  const role = localStorage.getItem('role');

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: t.nav.dashboard },
    { key: '/projects', icon: <ProjectOutlined />, label: t.nav.projects },
    { key: '/models', icon: <AppstoreOutlined />, label: t.nav.models },
    { key: '/data', icon: <CloudUploadOutlined />, label: t.data?.title || '数据管理' },
    { key: '/knowledge', icon: <DatabaseOutlined />, label: t.knowledge?.title || '知识库' },
    { key: '/knowledge-graph', icon: <ApartmentOutlined />, label: t.knowledge?.graph || '知识图谱' },
    { key: '/automl', icon: <ThunderboltOutlined />, label: t.automl?.title || '自动化建模' },
    { key: '/training', icon: <ExperimentOutlined />, label: t.training?.title || '模型训练' },
    { key: '/monitor', icon: <DashboardOutlined />, label: t.monitor?.title || '资源监控' },
    ...(role === 'admin' ? [{ key: '/admin/users', icon: <TeamOutlined />, label: t.nav.users }] : []),
  ];

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: role === 'admin' ? t.profile.admin : role === 'engineer' ? t.profile.engineer : t.profile.user,
      onClick: () => setProfileOpen(true),
    },
    ...(role === 'admin'
      ? [{ key: 'admin', icon: <TeamOutlined />, label: t.nav.users, onClick: () => navigate('/admin/users') }]
      : []),
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t.app.logout,
      onClick: () => { localStorage.clear(); navigate('/login'); },
    },
  ];

  const selectedKey = (() => {
    const p = location.pathname;
    if (p === '/') return '/';
    if (p.startsWith('/projects')) return '/projects';
    if (p.startsWith('/models')) return '/models';
    if (p.startsWith('/data')) return '/data';
    if (p.startsWith('/knowledge-graph')) return '/knowledge-graph';
    if (p.startsWith('/knowledge')) return '/knowledge';
    if (p.startsWith('/automl')) return '/automl';
    if (p.startsWith('/training')) return '/training';
        if (p.startsWith('/monitor')) return '/monitor';
    if (p.startsWith('/algorithms')) return '/algorithms';
    if (p.startsWith('/api-marketplace')) return '/api-marketplace';
    if (p.startsWith('/compute')) return '/compute';
    if (p.startsWith('/admin/users')) return '/admin/users';
    return '';
  })();

  const langLabel = lang === 'zh' ? '中文' : 'English';
  const username = localStorage.getItem('userId') || '-';
  const roleLabel = role === 'admin' ? t.profile.admin : role === 'engineer' ? t.profile.engineer : t.profile.user;
  const roleColor = role === 'admin' ? 'red' : role === 'engineer' ? 'blue' : 'green';

  return (
    <>
      <AntLayout style={{ minHeight: '100vh' }}>
        <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, color: '#fff' }}>{t.app.title}</h2>
          <Space>
            <Button
              size={"small"}
              type={lang === 'zh' ? 'primary' : 'default'}
              onClick={() => setLang('zh')}
              style={{ color: lang === 'zh' ? '#fff' : '#000' }}
            >
              {'中'}
            </Button>
            <Button
              size={"small"}
              type={lang === 'en' ? 'primary' : 'default'}
              onClick={() => setLang('en')}
              style={{ color: lang === 'en' ? '#fff' : '#000' }}
            >
              EN
            </Button>
            <Dropdown menu={{ items: userMenuItems }}>
              <Space style={{ cursor: 'pointer', color: '#fff' }}>
                <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1890ff' }} />
                <span>{roleLabel}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <AntLayout>
          <Sider width={180} style={{ background: '#fff' }}>
            <Menu
              mode={"inline"}
              selectedKeys={[selectedKey]}
              items={menuItems}
              onClick={({ key }) => navigate(key)}
              style={{ height: '100%', borderRight: 0 }}
            />
          </Sider>
          <Content style={{ padding: 24, background: '#f5f5f5', minHeight: 'calc(100vh - 64px)' }}>
            {children}
          </Content>
        </AntLayout>
      </AntLayout>
      <Modal title={'用户信息'} open={profileOpen} onCancel={() => setProfileOpen(false)} footer={null}>
        <Descriptions column={1} bordered size={"small"}>
          <Descriptions.Item label={'用户名'}>{username}</Descriptions.Item>
          <Descriptions.Item label={'角色'}>
            <Tag color={roleColor}>{roleLabel}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={'语言'}>{langLabel}</Descriptions.Item>
        </Descriptions>
      </Modal>
    </>
  );
}

