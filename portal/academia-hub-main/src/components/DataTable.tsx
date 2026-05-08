import React from 'react';

interface Column {
  key: string;
  label: string;
  render?: (value: any, row: any) => React.ReactNode;
}

interface DataTableProps {
  columns: Column[];
  data: any[];
  title?: string;
  actions?: React.ReactNode;
}

export default function DataTable({ columns, data, title, actions }: DataTableProps) {
  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {(title || actions) && (
        <div className="flex items-center justify-between p-4 border-b border-border">
          {title && <h3 className="font-display font-semibold">{title}</h3>}
          {actions}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="bg-muted/50">
              {columns.map(col => (
                <th key={col.key} className="text-left text-xs font-medium text-muted-foreground px-4 py-3 uppercase tracking-wider">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.map((row, i) => (
              <tr key={i} className="hover:bg-muted/30 transition-colors">
                {columns.map(col => (
                  <td key={col.key} className="px-4 py-3 text-sm">
                    {col.render ? col.render(row[col.key], row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
