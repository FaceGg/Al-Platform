import AppLayout from '../components/AppLayout'
import KnowledgeCenterContent from '../components/KnowledgeCenterContent'
import { useI18n } from '../i18n'

export default function KnowledgeCenterPage() {
  const { t } = useI18n()
  return (
    <AppLayout>
      <KnowledgeCenterContent t={t} />
    </AppLayout>
  )
}
