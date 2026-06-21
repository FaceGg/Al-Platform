import { Layout as AntLayout, Menu, Avatar, Dropdown, Space } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import { DashboardOutlined, ProjectOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons'

const { Header, Sider, Content } = AntLayout

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/projects', icon: <ProjectOutlined />, label: '项目' },
  ]

  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: '个人信息' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录',
        onClick: () => { localStorage.clear(); navigate('/login') }
      },
    ],
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0, color: '#fff' }}>ML 算法平台</h2>
        <Dropdown menu={userMenu}>
          <Space style={{ cursor: 'pointer', color: '#fff' }}>
            <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1890ff' }} />
            <span>{localStorage.getItem('role') === 'engineer' ? '工程师' : '用户'}</span>
          </Space>
        </Dropdown>
      </Header>
      <AntLayout>
        <Sider width={180} style={{ background: '#fff' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname === '/' ? '/' : location.pathname.startsWith('/projects') ? '/projects' : '']}
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
  )
}
