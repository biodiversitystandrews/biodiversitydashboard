// Parse every inline script without executing browser-dependent dashboard code.
const fs = require('fs');

new Function(fs.readFileSync('frontend/dashboard-config.js', 'utf8'));
console.log('frontend/dashboard-config.js: JavaScript parsed successfully');

for (const filename of ['frontend/index.html', 'frontend/polygon-analysis.html']) {
    const html = fs.readFileSync(filename, 'utf8');
    const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
    for (const match of scripts) {
        if (match[1].trim()) new Function(match[1]);
    }
    console.log(`${filename}: inline JavaScript parsed successfully`);
}
