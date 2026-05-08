import { useState, useCallback } from 'react';

export type InstitutionType = 'secondary' | 'tertiary' | null;

export type SecondaryRole = 'admin' | 'registry' | 'accountant' | 'teacher' | 'examiner' | 'student';
export type TertiaryRole = 'vc' | 'ict-admin' | 'accountant' | 'faculty-admin' | 'dept-admin' | 'lecturer' | 'examiner' | 'student';

export type UserRole = SecondaryRole | TertiaryRole;

export interface AppState {
  institutionType: InstitutionType;
  currentRole: UserRole | null;
  userName: string;
}

const SECONDARY_ROLES: { value: SecondaryRole; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'registry', label: 'Registry' },
  { value: 'accountant', label: 'Accountant' },
  { value: 'teacher', label: 'Teacher' },
  { value: 'examiner', label: 'Examiner' },
  { value: 'student', label: 'Student' },
];

const TERTIARY_ROLES: { value: TertiaryRole; label: string }[] = [
  { value: 'vc', label: 'VC / Provost' },
  { value: 'ict-admin', label: 'ICT Admin' },
  { value: 'accountant', label: 'Accountant' },
  { value: 'faculty-admin', label: 'Faculty Admin' },
  { value: 'dept-admin', label: 'Department Admin' },
  { value: 'lecturer', label: 'Lecturer' },
  { value: 'examiner', label: 'Examiner' },
  { value: 'student', label: 'Student' },
];

export { SECONDARY_ROLES, TERTIARY_ROLES };

export function useAppState() {
  const [state, setState] = useState<AppState>({
    institutionType: null,
    currentRole: null,
    userName: '',
  });

  const setInstitutionType = useCallback((type: InstitutionType) => {
    setState(s => ({ ...s, institutionType: type, currentRole: null }));
  }, []);

  const login = useCallback((role: UserRole, name: string) => {
    setState(s => ({ ...s, currentRole: role, userName: name }));
  }, []);

  const logout = useCallback(() => {
    setState({ institutionType: null, currentRole: null, userName: '' });
  }, []);

  return { state, setInstitutionType, login, logout };
}
