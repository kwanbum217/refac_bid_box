/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: {
    files: ['./src/app/templates/**/*.html'],
    extract: {
      html: (content) => {
        const classes = new Set();
        const classAttrRe = /class\s*=\s*["']([^"']*)["']/gi;
        let match;
        while ((match = classAttrRe.exec(content)) !== null) {
          const normalized = match[1]
            .replace(/\{%[^%]*%\}/g, ' ')
            .replace(/\{\{[^}]*\}\}/g, ' ');
          normalized.split(/\s+/).forEach((token) => {
            if (token) {
              classes.add(token);
            }
          });
        }
        const defaultMatches = content.match(/[^<>"'`\s]*[^<>"'`\s:]/g) || [];
        defaultMatches.forEach((token) => classes.add(token));
        return Array.from(classes);
      },
    },
  },
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#0073E6',
          hover: '#005BB3',
          light: '#E6F1FF',
        },
        harness: {
          bg: '#F9FAFB',
          sidebar: '#020B1A',
          border: '#E6E9EF',
          text: '#1F2937',
          muted: '#6B7280',
        },
      },
      borderRadius: {
        enterprise: '0.75rem',
      },
      boxShadow: {
        'h-sm': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        'h-md': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      },
    },
  },
  plugins: [],
};
