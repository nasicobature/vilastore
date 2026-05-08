import React, { createContext, useContext } from 'react';
import { useAppState, InstitutionType, UserRole } from './store';

interface AppContextType {
  institutionType: InstitutionType;
  currentRole: UserRole | null;
  userName: string;
  setInstitutionType: (type: InstitutionType) => void;
  login: (role: UserRole, name: string) => void;
  logout: () => void;
}

const AppContext = createContext<AppContextType | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { state, setInstitutionType, login, logout } = useAppState();

  return (
    <AppContext.Provider value={{ ...state, setInstitutionType, login, logout }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
