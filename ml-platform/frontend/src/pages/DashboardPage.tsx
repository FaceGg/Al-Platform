import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, List, Tag } from 'antd'
import { ProjectOutlined, PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'

export default function DashboardPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<any[]>([])
  const [stats, setStats] = useState({ total: 0 })

  useEffect(() => {
    apiClient.get('/projects').then((res) => {
      setProjects(res.data.items || [])
      setStats({ total: res.data.total || 0 })
    }).catch(() => {})
  }, [])

  return (
    <AppLayout>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card><Statistic title="项目总数" value={stats.total} prefix={<ProjectOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="运行中" value={0} prefix={<PlayCircleOutlined />} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="已完成" value={0} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="失败" value={0} prefix={<CloseCircleOutlined />} valueStyle={{ color: '#ff4d4f' }} /></Card>
        </Col>
      </Row>

      <Card title="最近项目" style={{ marginBottom: 16 }}>
        <List
          dataSource={projects.slice(0, 5)}
          renderItem={(item: any) => (
            <List.Item
              actions={[<a onClick={() => navigate('/projects/' + item.id)}>进入</a>]}
            >
              <List.Item.Meta title={item.name} description={item.description} />
            </List.Item>
          )}
          locale={{ emptyText: '暂无项目' }}
        />
      </Card>

      <Card title="快速开始">
        <Row gutter={16}>
          <Col span={8}>
            <Card hoverable size="small" onClick={() => navigate('/template/weld_quality')}>
              <Tag color="blue">焊接质量预测</Tag>
              <p style={{ marginTop: 8, color: '#666' }}>基于工艺参数预测焊接质量</p>
            </Card>
          </Col>
          <Col span={8}>
            <Card hoverable size="small" onClick={() => navigate('/projects')}>
              <Tag color="green">新建项目</Tag>
              <p style={{ marginTop: 8, color: '#666' }}>创建新的 ML 项目</p>
            </Card>
          </Col>
        </Row>
      </Card>
    </AppLayout>
  )
}
