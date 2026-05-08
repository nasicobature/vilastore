import React, { useState } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import StatCard from '@/components/StatCard';
import DataTable from '@/components/DataTable';
import { Button } from '@/components/ui/button';
import {
  Users, BookOpen, School, GraduationCap, CreditCard, ClipboardCheck,
  Plus, Download, Check, X, Edit, Eye
} from 'lucide-react';
import {
  dashboardStats, mockStudents, mockTeachers, mockSubjects, mockClasses,
  mockSessions, mockFees, mockPayments, mockResults
} from '@/lib/mock-data';
import { useApp } from '@/lib/context';

function AdminDashboard({ page }: { page: string }) {
  const stats = dashboardStats.secondary;
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Admin Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total Students" value={stats.totalStudents.toLocaleString()} icon={<Users size={20} />} trend="+12% this term" trendUp color="primary" />
        <StatCard title="Total Teachers" value={stats.totalTeachers} icon={<GraduationCap size={20} />} color="secondary" />
        <StatCard title="Classes" value={stats.totalClasses} icon={<School size={20} />} color="accent" />
        <StatCard title="Pass Rate" value={`${stats.passRate}%`} icon={<ClipboardCheck size={20} />} trend="+3.2%" trendUp color="info" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DataTable title="Recent Students" columns={[
          { key: 'id', label: 'ID' }, { key: 'name', label: 'Name' }, { key: 'class', label: 'Class' },
          { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Active' ? 'bg-secondary/10 text-secondary' : 'bg-muted text-muted-foreground'}`}>{v}</span> }
        ]} data={mockStudents.slice(0, 5)} />
        <DataTable title="Teachers" columns={[
          { key: 'name', label: 'Name' }, { key: 'subject', label: 'Subject' },
          { key: 'classes', label: 'Classes', render: (v: string[]) => v.join(', ') }
        ]} data={mockTeachers} />
      </div>
    </div>
  );
  if (page === 'users') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Manage Users</h2>
        <Button><Plus size={16} /> Add User</Button>
      </div>
      <DataTable columns={[
        { key: 'id', label: 'ID' }, { key: 'name', label: 'Name' }, { key: 'email', label: 'Email' },
        { key: 'class', label: 'Role/Class' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Active' ? 'bg-secondary/10 text-secondary' : 'bg-muted text-muted-foreground'}`}>{v}</span> },
        { key: 'actions', label: 'Actions', render: () => <div className="flex gap-1"><button className="p-1 hover:bg-muted rounded"><Edit size={14} /></button><button className="p-1 hover:bg-muted rounded"><Eye size={14} /></button></div> }
      ]} data={mockStudents} />
    </div>
  );
  if (page === 'classes') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Classes</h2>
        <Button><Plus size={16} /> Add Class</Button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {mockClasses.map(c => (
          <div key={c} className="bg-card border border-border rounded-xl p-4 text-center hover:shadow-md transition-shadow cursor-pointer">
            <School size={24} className="mx-auto mb-2 text-primary" />
            <p className="font-display font-semibold">{c}</p>
            <p className="text-xs text-muted-foreground mt-1">{Math.floor(Math.random() * 40 + 25)} students</p>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'subjects') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Subjects</h2>
        <Button><Plus size={16} /> Add Subject</Button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {mockSubjects.map(s => (
          <div key={s} className="bg-card border border-border rounded-xl p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
              <BookOpen size={18} className="text-primary" />
            </div>
            <div>
              <p className="font-medium text-sm">{s}</p>
              <p className="text-xs text-muted-foreground">{Math.floor(Math.random() * 5 + 1)} teachers</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'assign-teachers') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Assign Teachers</h2>
      <DataTable title="Teacher Assignments" columns={[
        { key: 'name', label: 'Teacher' }, { key: 'subject', label: 'Subject' },
        { key: 'classes', label: 'Assigned Classes', render: (v: string[]) => v.map(c => <span key={c} className="inline-block bg-primary/10 text-primary text-xs px-2 py-0.5 rounded-full mr-1">{c}</span>) },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm">Edit</Button> }
      ]} data={mockTeachers} actions={<Button><Plus size={16} /> New Assignment</Button>} />
    </div>
  );
  if (page === 'approve-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Approve Results</h2>
      <div className="space-y-3">
        {['SS2 Mathematics - First Term', 'SS1 English Language - First Term', 'JSS3 Physics - First Term'].map((r, i) => (
          <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
            <div>
              <p className="font-medium">{r}</p>
              <p className="text-sm text-muted-foreground">Submitted by {mockTeachers[i % mockTeachers.length].name}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm"><Eye size={14} /> Review</Button>
              <Button size="sm" className="bg-secondary hover:bg-secondary/90"><Check size={14} /> Approve</Button>
              <Button variant="destructive" size="sm"><X size={14} /> Reject</Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'settings') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">System Settings</h2>
      <div className="bg-card border border-border rounded-xl p-6 space-y-4 max-w-lg">
        {[{ label: 'School Name', value: 'Federal Government College, Lagos' },
          { label: 'Current Session', value: '2024/2025' },
          { label: 'Current Term', value: 'First Term' },
          { label: 'Grading System', value: 'WAEC Standard' }
        ].map(s => (
          <div key={s.label}>
            <label className="block text-sm font-medium mb-1">{s.label}</label>
            <input className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm" defaultValue={s.value} />
          </div>
        ))}
        <Button>Save Settings</Button>
      </div>
    </div>
  );
  return <p>Page not found</p>;
}

function RegistryDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Registry Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Registered Students" value="1,250" icon={<Users size={20} />} color="primary" />
        <StatCard title="New This Term" value="85" icon={<Plus size={20} />} trend="+15%" trendUp color="secondary" />
        <StatCard title="Active Classes" value="18" icon={<School size={20} />} color="accent" />
        <StatCard title="IDs Generated" value="1,180" icon={<CreditCard size={20} />} color="info" />
      </div>
      <DataTable title="Recently Registered" columns={[
        { key: 'id', label: 'Student ID' }, { key: 'name', label: 'Name' }, { key: 'class', label: 'Class' }, { key: 'gender', label: 'Gender' }
      ]} data={mockStudents.slice(0, 5)} />
    </div>
  );
  if (page === 'register') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Register New Student</h2>
      <div className="bg-card border border-border rounded-xl p-6 max-w-lg space-y-4">
        {['Full Name', 'Date of Birth', 'Gender', 'Parent/Guardian Name', 'Phone Number', 'Address'].map(f => (
          <div key={f}>
            <label className="block text-sm font-medium mb-1">{f}</label>
            <input className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm" placeholder={`Enter ${f.toLowerCase()}`} />
          </div>
        ))}
        <div>
          <label className="block text-sm font-medium mb-1">Assign Class</label>
          <select className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm">
            {mockClasses.map(c => <option key={c}>{c}</option>)}
          </select>
        </div>
        <Button><Plus size={16} /> Register Student</Button>
      </div>
    </div>
  );
  if (page === 'assign-class') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Assign Students to Classes</h2>
      <DataTable columns={[
        { key: 'id', label: 'ID' }, { key: 'name', label: 'Student' }, { key: 'class', label: 'Current Class' },
        { key: 'actions', label: '', render: () => <select className="px-2 py-1 rounded border border-input bg-background text-xs">{mockClasses.map(c => <option key={c}>{c}</option>)}</select> }
      ]} data={mockStudents} />
    </div>
  );
  if (page === 'sessions') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Academic Sessions & Terms</h2>
      <DataTable title="Sessions" columns={[
        { key: 'name', label: 'Session' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Current' ? 'bg-secondary/10 text-secondary' : 'bg-muted text-muted-foreground'}`}>{v}</span> }
      ]} data={mockSessions} actions={<Button size="sm"><Plus size={14} /> New Session</Button>} />
    </div>
  );
  if (page === 'student-ids') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Generate Student IDs</h2>
      <DataTable columns={[
        { key: 'id', label: 'Student ID' }, { key: 'name', label: 'Name' }, { key: 'class', label: 'Class' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Download size={14} /> Generate</Button> }
      ]} data={mockStudents} />
    </div>
  );
  return <p>Page not found</p>;
}

function AccountantDashboard({ page }: { page: string }) {
  const stats = dashboardStats.secondary;
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Accountant Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Fees Collected" value={`₦${(stats.feesCollected / 1e6).toFixed(1)}M`} icon={<CreditCard size={20} />} trend="+8%" trendUp color="secondary" />
        <StatCard title="Fees Pending" value={`₦${(stats.feesPending / 1e6).toFixed(1)}M`} icon={<CreditCard size={20} />} color="accent" />
        <StatCard title="Payments Today" value="12" icon={<CreditCard size={20} />} color="primary" />
        <StatCard title="Receipts Issued" value="890" icon={<ClipboardCheck size={20} />} color="info" />
      </div>
      <DataTable title="Recent Payments" columns={[
        { key: 'studentName', label: 'Student' }, { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'date', label: 'Date' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Paid' ? 'bg-secondary/10 text-secondary' : 'bg-accent/10 text-accent'}`}>{v}</span> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'fees') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">School Fees</h2>
        <Button><Plus size={16} /> Create Fee</Button>
      </div>
      <DataTable columns={[
        { key: 'name', label: 'Fee Type' }, { key: 'class', label: 'Class' },
        { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'term', label: 'Term' }, { key: 'session', label: 'Session' }
      ]} data={mockFees} />
    </div>
  );
  if (page === 'payments') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Record Payment</h2>
        <Button><Plus size={16} /> New Payment</Button>
      </div>
      <DataTable columns={[
        { key: 'receipt', label: 'Receipt #' }, { key: 'studentName', label: 'Student' },
        { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'date', label: 'Date' }, { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Paid' ? 'bg-secondary/10 text-secondary' : 'bg-accent/10 text-accent'}`}>{v}</span> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'receipts') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Receipts</h2>
      <DataTable columns={[
        { key: 'receipt', label: 'Receipt #' }, { key: 'studentName', label: 'Student' },
        { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'date', label: 'Date' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Download size={14} /> Download</Button> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'reports') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Financial Reports</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {['Revenue Summary', 'Outstanding Fees', 'Payment Trends', 'Class-wise Collection'].map(r => (
          <div key={r} className="bg-card border border-border rounded-xl p-6 text-center">
            <p className="font-medium mb-2">{r}</p>
            <p className="text-3xl font-display font-bold text-primary">₦{(Math.random() * 30 + 5).toFixed(1)}M</p>
            <Button variant="outline" size="sm" className="mt-3"><Download size={14} /> Export</Button>
          </div>
        ))}
      </div>
    </div>
  );
  return <p>Page not found</p>;
}

function TeacherDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Teacher Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="My Classes" value="3" icon={<School size={20} />} color="primary" />
        <StatCard title="My Students" value="124" icon={<Users size={20} />} color="secondary" />
        <StatCard title="Subjects" value="1" icon={<BookOpen size={20} />} color="accent" />
        <StatCard title="Pending Submissions" value="2" icon={<ClipboardCheck size={20} />} color="info" />
      </div>
      <DataTable title="My Class Assignments" columns={[
        { key: 'classes', label: 'Classes', render: (v: string[]) => v.join(', ') },
        { key: 'subject', label: 'Subject' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Eye size={14} /> View</Button> }
      ]} data={mockTeachers.slice(0, 1)} />
    </div>
  );
  if (page === 'my-classes') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Classes</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {['SS1', 'SS2'].map(c => (
          <div key={c} className="bg-card border border-border rounded-xl p-6 text-center">
            <School size={32} className="mx-auto mb-2 text-primary" />
            <p className="font-display text-xl font-bold">{c}</p>
            <p className="text-sm text-muted-foreground">Mathematics</p>
            <p className="text-xs text-muted-foreground mt-1">{Math.floor(Math.random() * 20 + 30)} students</p>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'my-students') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Students</h2>
      <DataTable columns={[
        { key: 'id', label: 'ID' }, { key: 'name', label: 'Name' }, { key: 'class', label: 'Class' }, { key: 'gender', label: 'Gender' }
      ]} data={mockStudents.filter(s => ['SS1', 'SS2'].includes(s.class))} />
    </div>
  );
  if (page === 'enter-scores') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Enter Scores</h2>
      <div className="flex gap-3 mb-4">
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm">
          <option>SS1</option><option>SS2</option>
        </select>
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm">
          <option>Test 1</option><option>Test 2</option><option>Assignment</option><option>Exam</option>
        </select>
      </div>
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <table className="w-full">
          <thead><tr className="bg-muted/50">
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">Student</th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">Score (max 20)</th>
          </tr></thead>
          <tbody className="divide-y divide-border">
            {mockStudents.filter(s => s.class === 'SS1' || s.class === 'SS2').map(s => (
              <tr key={s.id}><td className="px-4 py-2 text-sm">{s.name}</td><td className="px-4 py-2"><input type="number" max={20} className="w-20 px-2 py-1 rounded border border-input bg-background text-sm" /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button>Save Scores</Button>
    </div>
  );
  if (page === 'submit-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Submit Results</h2>
      {['SS1 Mathematics - First Term', 'SS2 Mathematics - First Term'].map((r, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="font-medium">{r}</p>
            <p className="text-sm text-muted-foreground">{i === 0 ? 'Complete' : 'Incomplete - 3 scores missing'}</p>
          </div>
          <Button size="sm" disabled={i === 1}>Submit for Review</Button>
        </div>
      ))}
    </div>
  );
  return <p>Page not found</p>;
}

function ExaminerDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Examiner Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard title="Pending Reviews" value="5" icon={<ClipboardCheck size={20} />} color="accent" />
        <StatCard title="Approved" value="12" icon={<Check size={20} />} color="secondary" />
        <StatCard title="Rejected" value="1" icon={<X size={20} />} color="primary" />
      </div>
    </div>
  );
  if (page === 'review-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Review Results</h2>
      {['SS2 Mathematics', 'SS1 English', 'JSS3 Physics', 'SS1 Chemistry', 'SS3 Biology'].map((r, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="font-medium">{r} - First Term</p>
            <p className="text-sm text-muted-foreground">Submitted by {mockTeachers[i % mockTeachers.length].name}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm"><Eye size={14} /> View</Button>
            <Button size="sm" className="bg-secondary hover:bg-secondary/90"><Check size={14} /> Approve</Button>
            <Button variant="destructive" size="sm"><X size={14} /></Button>
          </div>
        </div>
      ))}
    </div>
  );
  if (page === 'result-sheets') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Result Sheets</h2>
      <div className="flex gap-3 mb-4">
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm">{mockClasses.map(c => <option key={c}>{c}</option>)}</select>
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm"><option>First Term</option><option>Second Term</option><option>Third Term</option></select>
        <Button><Download size={16} /> Generate Sheet</Button>
      </div>
      <DataTable columns={[
        { key: 'subject', label: 'Subject' }, { key: 'test1', label: 'Test 1' }, { key: 'test2', label: 'Test 2' },
        { key: 'assignment', label: 'Assign.' }, { key: 'exam', label: 'Exam' }, { key: 'total', label: 'Total' },
        { key: 'grade', label: 'Grade', render: (v: string) => <span className="font-semibold text-primary">{v}</span> }
      ]} data={mockResults} />
    </div>
  );
  return <p>Page not found</p>;
}

function StudentDashboard({ page }: { page: string }) {
  const { userName } = useApp();
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Welcome, {userName}!</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="My Subjects" value="9" icon={<BookOpen size={20} />} color="primary" />
        <StatCard title="Average Score" value="83.6%" icon={<ClipboardCheck size={20} />} trend="+5%" trendUp color="secondary" />
        <StatCard title="Fees Status" value="Paid" icon={<CreditCard size={20} />} color="accent" />
        <StatCard title="Class Rank" value="3rd" icon={<GraduationCap size={20} />} color="info" />
      </div>
      <DataTable title="My Recent Results" columns={[
        { key: 'subject', label: 'Subject' }, { key: 'total', label: 'Total' },
        { key: 'grade', label: 'Grade', render: (v: string) => <span className="font-semibold text-primary">{v}</span> }
      ]} data={mockResults} />
    </div>
  );
  if (page === 'subjects') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Subjects</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {mockSubjects.slice(0, 9).map(s => (
          <div key={s} className="bg-card border border-border rounded-xl p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center"><BookOpen size={18} className="text-primary" /></div>
            <div><p className="font-medium text-sm">{s}</p><p className="text-xs text-muted-foreground">{mockTeachers[Math.floor(Math.random() * mockTeachers.length)].name}</p></div>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'test-scores') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Test Scores</h2>
      <DataTable columns={[
        { key: 'subject', label: 'Subject' }, { key: 'test1', label: 'Test 1 (20)' }, { key: 'test2', label: 'Test 2 (20)' }, { key: 'assignment', label: 'Assignment (10)' }
      ]} data={mockResults} />
    </div>
  );
  if (page === 'results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Exam Results</h2>
      <DataTable columns={[
        { key: 'subject', label: 'Subject' }, { key: 'test1', label: 'CA1' }, { key: 'test2', label: 'CA2' },
        { key: 'assignment', label: 'Assign.' }, { key: 'exam', label: 'Exam' }, { key: 'total', label: 'Total' },
        { key: 'grade', label: 'Grade', render: (v: string) => <span className="font-bold text-primary">{v}</span> }
      ]} data={mockResults} />
    </div>
  );
  if (page === 'pay-fees') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Pay School Fees</h2>
      <div className="bg-card border border-border rounded-xl p-6 max-w-md">
        <p className="text-sm text-muted-foreground mb-1">Outstanding Balance</p>
        <p className="text-3xl font-display font-bold text-primary mb-4">₦45,000</p>
        <div className="space-y-3">
          <div><label className="text-sm font-medium">Amount</label><input className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1" defaultValue="45000" /></div>
          <div><label className="text-sm font-medium">Payment Method</label>
            <select className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1"><option>Bank Transfer</option><option>Card Payment</option></select>
          </div>
          <Button className="w-full">Pay Now</Button>
        </div>
      </div>
    </div>
  );
  if (page === 'profile') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Profile</h2>
      <div className="bg-card border border-border rounded-xl p-6 max-w-md">
        <div className="w-20 h-20 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-2xl font-bold mx-auto mb-4">{userName.charAt(0)}</div>
        {[{ l: 'Name', v: userName }, { l: 'Student ID', v: 'STU001' }, { l: 'Class', v: 'SS2' }, { l: 'Department', v: 'Science' }, { l: 'Session', v: '2024/2025' }].map(f => (
          <div key={f.l} className="flex justify-between py-2 border-b border-border last:border-0"><span className="text-sm text-muted-foreground">{f.l}</span><span className="text-sm font-medium">{f.v}</span></div>
        ))}
      </div>
    </div>
  );
  return <p>Page not found</p>;
}

export default function SecondaryDashboard() {
  const { currentRole } = useApp();

  return (
    <DashboardLayout>
      {(page) => {
        switch (currentRole) {
          case 'admin': return <AdminDashboard page={page} />;
          case 'registry': return <RegistryDashboard page={page} />;
          case 'accountant': return <AccountantDashboard page={page} />;
          case 'teacher': return <TeacherDashboard page={page} />;
          case 'examiner': return <ExaminerDashboard page={page} />;
          case 'student': return <StudentDashboard page={page} />;
          default: return <p>Unknown role</p>;
        }
      }}
    </DashboardLayout>
  );
}
