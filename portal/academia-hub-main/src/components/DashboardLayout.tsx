import React, { useState } from 'react';
import { useApp } from '@/lib/context';
import { SECONDARY_ROLES, TERTIARY_ROLES } from '@/lib/store';
import {
  LayoutDashboard, Users, BookOpen, GraduationCap, CreditCard, ClipboardCheck,
  FileText, Settings, LogOut, Menu, X, ChevronDown, Bell, Search,
  Building2, School, Monitor, UserCheck, FolderOpen, Upload
} from 'lucide-react';

interface NavItem {
  label: string;
  icon: React.ReactNode;
  id: string;
}

function getNavItems(role: string, institution: string): NavItem[] {
  const iconSize = 18;
  
  if (institution === 'secondary') {
    switch (role) {
      case 'admin': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Manage Users', icon: <Users size={iconSize} />, id: 'users' },
        { label: 'Classes', icon: <School size={iconSize} />, id: 'classes' },
        { label: 'Subjects', icon: <BookOpen size={iconSize} />, id: 'subjects' },
        { label: 'Assign Teachers', icon: <UserCheck size={iconSize} />, id: 'assign-teachers' },
        { label: 'Approve Results', icon: <ClipboardCheck size={iconSize} />, id: 'approve-results' },
        { label: 'Settings', icon: <Settings size={iconSize} />, id: 'settings' },
      ];
      case 'registry': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Register Students', icon: <Users size={iconSize} />, id: 'register' },
        { label: 'Assign Classes', icon: <School size={iconSize} />, id: 'assign-class' },
        { label: 'Sessions & Terms', icon: <FolderOpen size={iconSize} />, id: 'sessions' },
        { label: 'Student IDs', icon: <CreditCard size={iconSize} />, id: 'student-ids' },
      ];
      case 'accountant': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'School Fees', icon: <CreditCard size={iconSize} />, id: 'fees' },
        { label: 'Payments', icon: <CreditCard size={iconSize} />, id: 'payments' },
        { label: 'Receipts', icon: <FileText size={iconSize} />, id: 'receipts' },
        { label: 'Reports', icon: <FileText size={iconSize} />, id: 'reports' },
      ];
      case 'teacher': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'My Classes', icon: <School size={iconSize} />, id: 'my-classes' },
        { label: 'My Students', icon: <Users size={iconSize} />, id: 'my-students' },
        { label: 'Enter Scores', icon: <ClipboardCheck size={iconSize} />, id: 'enter-scores' },
        { label: 'Submit Results', icon: <Upload size={iconSize} />, id: 'submit-results' },
      ];
      case 'examiner': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Review Results', icon: <ClipboardCheck size={iconSize} />, id: 'review-results' },
        { label: 'Result Sheets', icon: <FileText size={iconSize} />, id: 'result-sheets' },
      ];
      case 'student': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'My Subjects', icon: <BookOpen size={iconSize} />, id: 'subjects' },
        { label: 'Test Scores', icon: <ClipboardCheck size={iconSize} />, id: 'test-scores' },
        { label: 'Exam Results', icon: <GraduationCap size={iconSize} />, id: 'results' },
        { label: 'Pay Fees', icon: <CreditCard size={iconSize} />, id: 'pay-fees' },
        { label: 'My Profile', icon: <Users size={iconSize} />, id: 'profile' },
      ];
      default: return [];
    }
  } else {
    switch (role) {
      case 'vc': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Approve Results', icon: <ClipboardCheck size={iconSize} />, id: 'approve-results' },
        { label: 'Analytics', icon: <FileText size={iconSize} />, id: 'analytics' },
        { label: 'Faculties', icon: <Building2 size={iconSize} />, id: 'faculties' },
      ];
      case 'ict-admin': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'CBT Exams', icon: <Monitor size={iconSize} />, id: 'cbt-exams' },
        { label: 'Questions Bank', icon: <FileText size={iconSize} />, id: 'questions' },
        { label: 'Manage Users', icon: <Users size={iconSize} />, id: 'users' },
        { label: 'Grading System', icon: <Settings size={iconSize} />, id: 'grading' },
      ];
      case 'accountant': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'School Fees', icon: <CreditCard size={iconSize} />, id: 'fees' },
        { label: 'Payments', icon: <CreditCard size={iconSize} />, id: 'payments' },
        { label: 'Receipts', icon: <FileText size={iconSize} />, id: 'receipts' },
        { label: 'Reports', icon: <FileText size={iconSize} />, id: 'reports' },
      ];
      case 'faculty-admin': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Departments', icon: <Building2 size={iconSize} />, id: 'departments' },
        { label: 'Performance', icon: <FileText size={iconSize} />, id: 'performance' },
        { label: 'Approve Results', icon: <ClipboardCheck size={iconSize} />, id: 'approve-results' },
      ];
      case 'dept-admin': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Students', icon: <Users size={iconSize} />, id: 'students' },
        { label: 'Courses', icon: <BookOpen size={iconSize} />, id: 'courses' },
        { label: 'Lecturers', icon: <GraduationCap size={iconSize} />, id: 'lecturers' },
        { label: 'Submit Results', icon: <Upload size={iconSize} />, id: 'submit-results' },
      ];
      case 'lecturer': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'My Courses', icon: <BookOpen size={iconSize} />, id: 'my-courses' },
        { label: 'My Students', icon: <Users size={iconSize} />, id: 'my-students' },
        { label: 'Enter Scores', icon: <ClipboardCheck size={iconSize} />, id: 'enter-scores' },
        { label: 'Materials', icon: <Upload size={iconSize} />, id: 'materials' },
        { label: 'Submit Results', icon: <Upload size={iconSize} />, id: 'submit-results' },
      ];
      case 'examiner': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Review Results', icon: <ClipboardCheck size={iconSize} />, id: 'review-results' },
        { label: 'Verify Grading', icon: <FileText size={iconSize} />, id: 'verify-grading' },
      ];
      case 'student': return [
        { label: 'Dashboard', icon: <LayoutDashboard size={iconSize} />, id: 'dashboard' },
        { label: 'Register Courses', icon: <BookOpen size={iconSize} />, id: 'register-courses' },
        { label: 'Pay Fees', icon: <CreditCard size={iconSize} />, id: 'pay-fees' },
        { label: 'CBT Exams', icon: <Monitor size={iconSize} />, id: 'cbt-exams' },
        { label: 'Results', icon: <GraduationCap size={iconSize} />, id: 'results' },
        { label: 'Transcript', icon: <FileText size={iconSize} />, id: 'transcript' },
        { label: 'Payments', icon: <CreditCard size={iconSize} />, id: 'payment-history' },
      ];
      default: return [];
    }
  }
}

interface DashboardLayoutProps {
  children: (activePage: string) => React.ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  const { currentRole, institutionType, userName, logout } = useApp();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activePage, setActivePage] = useState('dashboard');

  const navItems = getNavItems(currentRole || '', institutionType || '');
  const roles = institutionType === 'secondary' ? SECONDARY_ROLES : TERTIARY_ROLES;
  const roleLabel = roles.find(r => r.value === currentRole)?.label || '';
  const institutionLabel = institutionType === 'secondary' ? 'Secondary School' : 'Tertiary Institution';

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-0 -ml-64'} md:${sidebarOpen ? 'w-64' : 'w-16'} transition-all duration-300 bg-sidebar flex flex-col flex-shrink-0`}>
        <div className="p-4 border-b border-sidebar-border">
          <div className="flex items-center gap-2">
            <GraduationCap className="text-sidebar-primary-foreground" size={28} />
            <div className={sidebarOpen ? 'block' : 'hidden'}>
              <h1 className="font-display text-sm font-bold text-sidebar-foreground">EduPortal</h1>
              <p className="text-xs text-sidebar-foreground/60">{institutionLabel}</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => setActivePage(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                activePage === item.id
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'
              }`}
            >
              {item.icon}
              <span className={sidebarOpen ? 'block' : 'hidden'}>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="p-3 border-t border-sidebar-border">
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-sidebar-foreground/70 hover:bg-destructive/20 hover:text-destructive transition-colors"
          >
            <LogOut size={18} />
            <span className={sidebarOpen ? 'block' : 'hidden'}>Logout</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 bg-card border-b border-border flex items-center justify-between px-4 md:px-6 flex-shrink-0">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
              {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div className="hidden md:flex items-center gap-2 bg-muted rounded-lg px-3 py-2">
              <Search size={16} className="text-muted-foreground" />
              <input type="text" placeholder="Search..." className="bg-transparent border-none outline-none text-sm w-48" />
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button className="relative p-2 rounded-lg hover:bg-muted transition-colors">
              <Bell size={20} />
              <span className="absolute top-1 right-1 w-2 h-2 bg-destructive rounded-full" />
            </button>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-sm font-semibold">
                {userName.charAt(0)}
              </div>
              <div className="hidden md:block">
                <p className="text-sm font-medium">{userName}</p>
                <p className="text-xs text-muted-foreground">{roleLabel}</p>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          {children(activePage)}
        </main>
      </div>
    </div>
  );
}
