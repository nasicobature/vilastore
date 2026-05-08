import { AppProvider, useApp } from '@/lib/context';
import InstitutionSelector from '@/pages/InstitutionSelector';
import LoginPage from '@/pages/LoginPage';
import SecondaryDashboard from '@/pages/SecondaryDashboard';
import TertiaryDashboard from '@/pages/TertiaryDashboard';

function AppContent() {
  const { institutionType, currentRole } = useApp();

  if (!institutionType) return <InstitutionSelector />;
  if (!currentRole) return <LoginPage />;
  if (institutionType === 'secondary') return <SecondaryDashboard />;
  return <TertiaryDashboard />;
}

const Index = () => (
  <AppProvider>
    <AppContent />
  </AppProvider>
);

export default Index;
