<?php
/*
 * Owner API for Paint My House: /api/plugin/fpp-paint-my-house/...
 *
 * These routes live on FPP's own web server, so they are protected exactly as
 * FPP's UI is (set a UI password in FPP if the network is shared). They proxy to
 * the daemon's admin port, which only listens on 127.0.0.1 and also requires
 * the admin token stored in the plugin data directory.
 */

function pmhDataDir() {
    global $settings;
    $media = isset($settings['mediaDirectory']) ? $settings['mediaDirectory'] : '/home/fpp/media';
    return $media . '/plugindata/fpp-paint-my-house';
}

function pmhAdminPort() {
    $f = pmhDataDir() . '/settings.json';
    if (is_readable($f)) {
        $j = json_decode(file_get_contents($f), true);
        if (is_array($j) && isset($j['admin_port']) && is_int($j['admin_port'])) {
            return $j['admin_port'];
        }
    }
    return 8098;
}

function pmhProxy($method, $path, $body = null) {
    $tokFile = pmhDataDir() . '/admin.token';
    $token = is_readable($tokFile) ? trim(file_get_contents($tokFile)) : '';
    $headers = "X-PMH-Admin: " . $token . "\r\nContent-Type: application/json\r\n";
    $opts = array('http' => array(
        'method' => $method,
        'header' => $headers,
        'timeout' => 10,
        'ignore_errors' => true,
    ));
    if ($body !== null) {
        $opts['http']['content'] = $body;
    }
    $url = 'http://127.0.0.1:' . pmhAdminPort() . $path;
    $res = @file_get_contents($url, false, stream_context_create($opts));
    if ($res === false) {
        http_response_code(503);
        header('Content-Type: application/json');
        return json_encode(array('ok' => false, 'error' => 'Paint My House service is not running. Restart FPP (fppd) or use "Restart service" on the plugin page.'));
    }
    $status = 200;
    $hdrs = function_exists('http_get_last_response_headers') ? http_get_last_response_headers() : (isset($http_response_header) ? $http_response_header : array());
    if (isset($hdrs[0]) && preg_match('/\s(\d{3})\s?/', $hdrs[0], $m)) {
        $status = intval($m[1]);
    }
    http_response_code($status);
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    return $res;
}

function pmhBody() {
    $b = file_get_contents('php://input');
    return ($b === false || $b === '') ? '{}' : $b;
}

function getEndpointsfpppaintmyhouse() {
    $eps = array(
        array('method' => 'GET', 'endpoint' => 'status', 'callback' => 'pmhStatus'),
        array('method' => 'GET', 'endpoint' => 'layout', 'callback' => 'pmhLayout'),
        array('method' => 'GET', 'endpoint' => 'frame', 'callback' => 'pmhFrame'),
        array('method' => 'GET', 'endpoint' => 'model', 'callback' => 'pmhModel'),
        array('method' => 'PUT', 'endpoint' => 'settings', 'callback' => 'pmhSettings'),
        array('method' => 'POST', 'endpoint' => 'paint', 'callback' => 'pmhPaint'),
        array('method' => 'POST', 'endpoint' => 'action', 'callback' => 'pmhAction'),
        array('method' => 'POST', 'endpoint' => 'looks/:op', 'callback' => 'pmhLooks'),
        array('method' => 'POST', 'endpoint' => 'service/restart', 'callback' => 'pmhRestartService'),
    );
    return $eps;
}

function pmhStatus() { return pmhProxy('GET', '/admin/status'); }
function pmhLayout() { return pmhProxy('GET', '/admin/layout'); }
function pmhFrame() { return pmhProxy('GET', '/admin/frame'); }
function pmhModel() { return pmhProxy('GET', '/admin/model'); }
function pmhSettings() { return pmhProxy('PUT', '/admin/settings', pmhBody()); }
function pmhPaint() { return pmhProxy('POST', '/admin/paint', pmhBody()); }
function pmhAction() { return pmhProxy('POST', '/admin/action', pmhBody()); }

function pmhLooks() {
    $op = params('op');
    if (!in_array($op, array('save', 'load', 'delete'), true)) {
        http_response_code(404);
        return json_encode(array('ok' => false, 'error' => 'unknown op'));
    }
    return pmhProxy('POST', '/admin/looks/' . $op, pmhBody());
}

function pmhRestartService() {
    $script = __DIR__ . '/scripts/pmh_service.sh';
    exec('/bin/bash ' . escapeshellarg($script) . ' restart > /dev/null 2>&1 &');
    header('Content-Type: application/json');
    return json_encode(array('ok' => true));
}
?>
