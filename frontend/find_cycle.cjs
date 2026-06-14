const fs = require('fs');
const path = require('path');

const imports = {};
const srcDir = path.join(__dirname, 'src');

function walk(dir) {
    fs.readdirSync(dir).forEach(f => {
        const p = path.join(dir, f);
        if (fs.statSync(p).isDirectory()) {
            walk(p);
        } else if (p.endsWith('.ts') || p.endsWith('.tsx')) {
            const relPath = path.relative(srcDir, p).replace(/\\/g, '/');
            const content = fs.readFileSync(p, 'utf8');
            const matches = content.match(/from\s+['"](.*?)['"]/g) || [];
            imports[relPath] = matches.map(m => {
                let target = m.replace(/from\s+['"]|['"]/g, '').trim();
                if (target.startsWith('@/')) {
                    target = target.replace('@/', '');
                } else if (target.startsWith('.')) {
                    target = path.normalize(path.join(path.dirname(relPath), target)).replace(/\\/g, '/');
                } else {
                    return null;
                }
                
                if (!target.endsWith('.ts') && !target.endsWith('.tsx')) {
                    if (fs.existsSync(path.join(srcDir, target + '.ts'))) target += '.ts';
                    else if (fs.existsSync(path.join(srcDir, target + '.tsx'))) target += '.tsx';
                    else if (fs.existsSync(path.join(srcDir, target, 'index.ts'))) target += '/index.ts';
                    else if (fs.existsSync(path.join(srcDir, target, 'index.tsx'))) target += '/index.tsx';
                }
                return target;
            }).filter(Boolean);
        }
    });
}

walk(srcDir);

let allCycles = [];

for (const startNode of Object.keys(imports)) {
    const visited = new Set();
    const stack = [];

    function dfs(node) {
        if (stack.includes(node)) {
            const idx = stack.indexOf(node);
            const cycle = stack.slice(idx);
            
            // Deduplicate cycles
            const cycleStr = cycle.slice().sort().join(',');
            if (!allCycles.some(c => c.slice().sort().join(',') === cycleStr)) {
                allCycles.push(cycle);
            }
            return;
        }
        if (visited.has(node)) return;

        visited.add(node);
        stack.push(node);

        for (const neighbor of (imports[node] || [])) {
            dfs(neighbor);
        }

        stack.pop();
    }

    dfs(startNode);
}

if (allCycles.length > 0) {
    allCycles.forEach(c => console.log('CYCLE FOUND:\n' + c.join(' -> ') + ' -> ' + c[0]));
} else {
    console.log('NO CYCLES FOUND');
}
