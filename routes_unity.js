const express = require('express');
const multer = require('multer');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const router = express.Router();
const storage = multer.memoryStorage();
const upload = multer({ storage, limits: { fileSize: 100 * 1024 * 1024 } });

const PYTHON = 'python3';
const SCRIPT = path.join(__dirname, 'unity_process.py');

function getTmpPath(ext) {
    return path.join(os.tmpdir(), `unity_${crypto.randomBytes(8).toString('hex')}${ext}`);
}

function runPython(args, timeout = 120000) {
    return new Promise((resolve, reject) => {
        execFile(PYTHON, [SCRIPT, ...args], { timeout }, (err, stdout, stderr) => {
            if (err) {
                reject(new Error(stderr || err.message));
            } else {
                resolve(stdout);
            }
        });
    });
}

// List all PathIDs
router.post('/ListPathIds', upload.single('assetFile'), async (req, res) => {
    if (!req.file) return res.status(400).send('No file uploaded');
    const inputPath = getTmpPath('.bundle');
    const outputPath = getTmpPath('.json');
    try {
        fs.writeFileSync(inputPath, req.file.buffer);
        await runPython(['list', inputPath, outputPath]);
        const result = fs.readFileSync(outputPath, 'utf-8');
        res.setHeader('Content-Type', 'application/json');
        res.send(result);
    } catch (e) {
        console.error('ListPathIds error:', e.message);
        res.status(500).send('Error parsing file: ' + e.message);
    } finally {
        try { fs.unlinkSync(inputPath); } catch(e) {}
        try { fs.unlinkSync(outputPath); } catch(e) {}
    }
});

// Export dump
router.post('/ExportDump', upload.single('assetFile'), async (req, res) => {
    const { pathId } = req.body;
    if (!req.file || !pathId) return res.status(400).send('Missing file or pathId');
    const inputPath = getTmpPath('.bundle');
    const outputPath = getTmpPath('.txt');
    try {
        fs.writeFileSync(inputPath, req.file.buffer);
        await runPython(['dump', inputPath, outputPath, pathId]);
        const result = fs.readFileSync(outputPath, 'utf-8');
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        res.setHeader('Content-Disposition', `attachment; filename="dump_${pathId}.txt"`);
        res.send(result);
    } catch (e) {
        console.error('ExportDump error:', e.message);
        res.status(500).send('Error: ' + e.message);
    } finally {
        try { fs.unlinkSync(inputPath); } catch(e) {}
        try { fs.unlinkSync(outputPath); } catch(e) {}
    }
});

// Compare files
router.post('/CompareFiles', upload.fields([
    { name: 'originalFile', maxCount: 1 },
    { name: 'modifiedFile', maxCount: 1 }
]), async (req, res) => {
    if (!req.files || !req.files.originalFile || !req.files.modifiedFile) {
        return res.status(400).send('Both files required');
    }
    const origPath = getTmpPath('.orig');
    const modPath = getTmpPath('.mod');
    const outputPath = getTmpPath('.json');
    try {
        fs.writeFileSync(origPath, req.files.originalFile[0].buffer);
        fs.writeFileSync(modPath, req.files.modifiedFile[0].buffer);
        await runPython(['compare', origPath, modPath, outputPath]);
        const result = fs.readFileSync(outputPath, 'utf-8');
        res.setHeader('Content-Type', 'application/json');
        res.send(result);
    } catch (e) {
        console.error('CompareFiles error:', e.message);
        res.status(500).send('Error comparing: ' + e.message);
    } finally {
        try { fs.unlinkSync(origPath); } catch(e) {}
        try { fs.unlinkSync(modPath); } catch(e) {}
        try { fs.unlinkSync(outputPath); } catch(e) {}
    }
});

// Import dump
router.post('/ImportDump', upload.fields([
    { name: 'assetFile', maxCount: 1 },
    { name: 'dumpFile', maxCount: 1 }
]), async (req, res) => {
    if (!req.files || !req.files.assetFile || !req.files.dumpFile) {
        return res.status(400).send('Missing files');
    }
    try {
        // Basic import - return original for now
        const assetFile = req.files.assetFile[0];
        res.setHeader('Content-Type', 'application/octet-stream');
        res.setHeader('Content-Disposition', `attachment; filename="${assetFile.originalname}"`);
        res.send(assetFile.buffer);
    } catch (e) {
        console.error('ImportDump error:', e.message);
        res.status(500).send('Error: ' + e.message);
    }
});

// Holograma Arma - Color Process
router.post('/HoloArmaColorProcess', upload.single('assetFile'), async (req, res) => {
    if (!req.file) return res.status(400).send('No file uploaded');
    const { mode, oloColorHex, borderColorHex, wallColorHex } = req.body;
    const inputPath = getTmpPath('.bundle');
    const outputPath = getTmpPath('.modified');
    try {
        fs.writeFileSync(inputPath, req.file.buffer);
        const args = [
            'holo', inputPath, outputPath,
            mode || 'bordes',
            oloColorHex || '#00FF00',
            borderColorHex || 'null',
            wallColorHex || 'null'
        ];
        await runPython(args);
        const result = fs.readFileSync(outputPath);
        res.setHeader('Content-Type', 'application/octet-stream');
        res.setHeader('Content-Disposition', `attachment; filename="${req.file.originalname}"`);
        res.send(result);
    } catch (e) {
        console.error('HoloArmaColorProcess error:', e.message);
        res.status(500).send('Error processing: ' + e.message);
    } finally {
        try { fs.unlinkSync(inputPath); } catch(e) {}
        try { fs.unlinkSync(outputPath); } catch(e) {}
    }
});

// Holograma Personaje - Color Process
router.post('/HoloPersonajeProcess', upload.single('assetFile'), async (req, res) => {
    if (!req.file) return res.status(400).send('No file uploaded');
    const { mode, oloColorHex, borderColorHex, wallColorHex } = req.body;
    const inputPath = getTmpPath('.bundle');
    const outputPath = getTmpPath('.modified');
    try {
        fs.writeFileSync(inputPath, req.file.buffer);
        const args = [
            'holo', inputPath, outputPath,
            mode || 'bordes',
            oloColorHex || '#00FF00',
            borderColorHex || 'null',
            wallColorHex || 'null'
        ];
        await runPython(args);
        const result = fs.readFileSync(outputPath);
        res.setHeader('Content-Type', 'application/octet-stream');
        res.setHeader('Content-Disposition', `attachment; filename="${req.file.originalname}"`);
        res.send(result);
    } catch (e) {
        console.error('HoloPersonajeProcess error:', e.message);
        res.status(500).send('Error processing: ' + e.message);
    } finally {
        try { fs.unlinkSync(inputPath); } catch(e) {}
        try { fs.unlinkSync(outputPath); } catch(e) {}
    }
});

module.exports = router;
