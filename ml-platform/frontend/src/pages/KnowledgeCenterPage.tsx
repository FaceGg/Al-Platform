import AppLayout from '../components/AppLayout'
import PageHeading from '../components/PageHeading'
import KnowledgeCenterContent from '../components/KnowledgeCenterContent'
import { useI18n } from '../i18n'

export default function KnowledgeCenterPage() {
  const { t } = useI18n()
  return (
    <AppLayout>
      <PageHeading section="agent" navKey="knowledge_center" />
      <KnowledgeCenterContent t={t} />
    </AppLayout>
  )
}
