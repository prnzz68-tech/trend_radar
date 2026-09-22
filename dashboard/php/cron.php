<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') exit(1);
require __DIR__ . '/collect.php';
require __DIR__ . '/telegram.php';
$config = radar_config();
try { radar_collect($config); }
catch (Throwable $error) { error_log('Trend Radar collect: ' . $error->getMessage()); }
try { radar_send_daily($config); }
catch (Throwable $error) { error_log('Trend Radar digest: ' . $error->getMessage()); }
