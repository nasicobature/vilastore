import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
  color?: 'primary' | 'secondary' | 'accent' | 'info';
}

const colorMap = {
  primary: 'bg-primary/10 text-primary',
  secondary: 'bg-secondary/10 text-secondary',
  accent: 'bg-accent/10 text-accent',
  info: 'bg-info/10 text-info',
};

export default function StatCard({ title, value, icon, trend, trendUp, color = 'primary' }: StatCardProps) {
  return (
    <div className="bg-card rounded-xl border border-border p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="text-2xl font-display font-bold mt-1">{value}</p>
          {trend && (
            <p className={`text-xs mt-1 ${trendUp ? 'text-secondary' : 'text-destructive'}`}>
              {trendUp ? '↑' : '↓'} {trend}
            </p>
          )}
        </div>
        <div className={`p-2.5 rounded-lg ${colorMap[color]}`}>{icon}</div>
      </div>
    </div>
  );
}
