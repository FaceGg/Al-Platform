import { useEffect, useState } from "react";
import { Card, Row, Col, Button, Modal, Form, Input, message, Typography } from "antd";
import { PlusOutlined, DeleteOutlined, BookOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Paragraph } = Typography;

export default function KnowledgeBasePage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [bases, setBases] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    apiClient.get("/knowledge/bases")
      .then((res) => setBases(res.data.items || res.data || []))
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const deleteBase = (id: string, name: string) => {
    Modal.confirm({
      title: t.knowledge.delete_kb + " " + name + "?",
      content: t.knowledge.delete_kb_desc,
      okText: t.common.confirm,
      okType: "danger",
      cancelText: t.common.cancel,
      onOk: async () => {
        try {
          await apiClient.delete("/knowledge/bases/" + id);
          message.success(t.common.success);
          load();
        } catch (e: any) {
          message.error(e.response?.data?.detail || t.common.error);
        }
      },
    });
  };

  const createBase = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases", values);
      message.success(t.common.success);
      setModalOpen(false);
      form.resetFields();
      load();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>{t.knowledge.title}</h3>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          {t.knowledge.create}
        </Button>
      </div>
      <Row gutter={[16, 16]}>
        {bases.map((kb: any) => (
          <Col xs={24} sm={12} md={8} key={kb.id}>
            <Card
              hoverable
              loading={loading}
              actions={[
                <Button type="link" key="enter" onClick={() => navigate("/knowledge/" + kb.id)}>
                  {t.common.confirm}
                </Button>,
                <Button type="link" danger key="del" icon={<DeleteOutlined />}
                  onClick={(e) => { e.stopPropagation(); deleteBase(kb.id, kb.name); }}>
                  {t.common.delete}
                </Button>,
              ]}
            >
              <Card.Meta
                avatar={<BookOutlined style={{ fontSize: 24, color: "#1890ff" }} />}
                title={<a onClick={() => navigate("/knowledge/" + kb.id)}>{kb.name}</a>}
                description={
                  <div>
                    <Paragraph ellipsis={{ rows: 2 }} type="secondary">
                      {kb.description || "-"}
                    </Paragraph>
                    <Text type="secondary">{t.knowledge.doc_count}: {kb.doc_count ?? 0}</Text>
                  </div>
                }
              />
            </Card>
          </Col>
        ))}
        {!loading && bases.length === 0 && (
          <Col span={24}>
            <Card><Text type="secondary">{t.common.loading}</Text></Card>
          </Col>
        )}
      </Row>
      <Modal title={t.knowledge.create} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        <Form form={form} onFinish={createBase} layout="vertical">
          <Form.Item name="name" label={t.knowledge.name} rules={[{ required: true }]}>
            <Input placeholder={t.knowledge.name} />
          </Form.Item>
          <Form.Item name="description" label={t.knowledge.desc}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
