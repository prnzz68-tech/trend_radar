<?php
declare(strict_types=1);
require_once __DIR__ . '/common.php';

function radar_youtube_request(string $endpoint, array $parameters): array {
    static $lastRequestAt = 0.0;
    $blocked = radar_read_state()['youtubeBlockedUntil'] ?? null;
    if ($blocked && radar_ms($blocked) > time() * 1000) throw new RadarHttpException('Лимит YouTube API достигнут. Повторите позже.', 429);
    $url = 'https://www.googleapis.com/youtube/v3/' . $endpoint . '?' . http_build_query($parameters);
    for ($attempt = 0; $attempt < 3; $attempt++) {
        $gap = 1.0 - (microtime(true) - $lastRequestAt);
        if ($gap > 0) usleep((int) ($gap * 1000000));
        $lastRequestAt = microtime(true);
        $headers = [];
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 20,
            CURLOPT_HTTPHEADER => ['Accept: application/json'],
            CURLOPT_HEADERFUNCTION => function ($curl, string $line) use (&$headers): int {
                $split = explode(':', $line, 2);
                if (count($split) === 2) $headers[strtolower(trim($split[0]))] = trim($split[1]);
                return strlen($line);
            }
        ]);
        $body = curl_exec($curl);
        $status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
        $networkError = curl_error($curl);
        curl_close($curl);
        $data = is_string($body) ? json_decode($body, true) : null;
        if ($status >= 200 && $status < 300 && is_array($data)) return $data;
        $reason = (string) ($data['error']['errors'][0]['reason'] ?? '');
        $message = (string) ($data['error']['message'] ?? ($networkError ?: "YouTube API: HTTP $status"));
        if ($status === 403 && in_array($reason, ['quotaExceeded', 'dailyLimitExceeded', 'dailyLimitExceededUnreg'], true)) {
            radar_update_state(function (array &$state): void { $state['youtubeBlockedUntil'] = gmdate('Y-m-d\TH:i:s\Z', time() + 86400); });
            throw new RadarHttpException('Дневной лимит YouTube API исчерпан. Запросы приостановлены на 24 часа.', 429);
        }
        $throttled = $status === 429 || ($status === 403 && in_array($reason, ['rateLimitExceeded', 'userRateLimitExceeded'], true));
        $retryAfter = max(0, (int) ($headers['retry-after'] ?? 0));
        if ($throttled && $attempt === 2) {
            radar_update_state(function (array &$state) use ($retryAfter): void { $state['youtubeBlockedUntil'] = gmdate('Y-m-d\TH:i:s\Z', time() + ($retryAfter ?: 3600)); });
            throw new RadarHttpException('YouTube ограничил частоту запросов. Повторите позже.', 429);
        }
        if (!$throttled && !in_array($status, [0, 500, 502, 503, 504], true)) throw new RuntimeException($message);
        if ($attempt === 2) throw new RuntimeException($message);
        sleep($retryAfter ?: min(30, 2 ** ($attempt + 1)));
    }
    throw new RuntimeException('YouTube API недоступен');
}

function radar_video_item(array $video, bool $global = false): array {
    $id = (string) ($video['id'] ?? '');
    $snippet = $video['snippet'] ?? [];
    $title = (string) ($snippet['title'] ?? 'Видео');
    $statistics = $video['statistics'] ?? [];
    return [
        'id' => ($global ? 'global-youtube-' : 'youtube-') . $id,
        'platform' => 'YouTube', 'title' => $title, 'creator' => (string) ($snippet['channelTitle'] ?? ''),
        'url' => 'https://www.youtube.com/watch?v=' . rawurlencode($id),
        'topic' => $global ? 'Без тематического фильтра' : (preg_match('/егэ/iu', $title) ? 'Курсы подготовки к ЕГЭ' : 'Онлайн-обучение'),
        'format' => 'Короткое видео', 'views' => (int) ($statistics['viewCount'] ?? 0),
        'likes' => (int) ($statistics['likeCount'] ?? 0), 'comments' => (int) ($statistics['commentCount'] ?? 0),
        'shares' => null, 'reach' => null,
        'publishedAt' => (string) ($snippet['publishedAt'] ?? radar_now()), 'collectedAt' => radar_now(),
        'source' => $global ? 'global-youtube' : 'youtube'
    ];
}

function radar_is_relevant(array $video, string $query, string $region): bool {
    if ($query !== 'онлайн обучение и курсы ЕГЭ') return true;
    $title = (string) ($video['snippet']['title'] ?? '');
    if ($region === 'RU' && !preg_match('/[а-яё]/iu', $title)) return false;
    if (preg_match('/егэ/iu', $title)) return (bool) preg_match('/курс|онлайн|online|школ|обуч|подготовк|задани|разбор|балл|урок|экзамен/iu', $title);
    return (bool) (preg_match('/онлайн|online|on-line|дистанцион|zoom/iu', $title) && preg_match('/обуч|курс|школ|урок|образован|учеб|education|learn|class|school/iu', $title));
}

function radar_fetch_thematic(array $config, array $settings): array {
    $query = (string) $settings['query'];
    $terms = $query === 'онлайн обучение и курсы ЕГЭ'
        ? ['"онлайн обучение"', '"онлайн курс"', 'ЕГЭ подготовка', 'ЕГЭ разбор задания', 'ЕГЭ онлайн курс'] : [$query];
    $ids = []; $errors = [];
    foreach ($terms as $term) {
        try {
            $response = radar_youtube_request('search', [
                'part' => 'snippet', 'type' => 'video', 'videoDuration' => 'short', 'order' => 'viewCount',
                'maxResults' => 15, 'publishedAfter' => gmdate('Y-m-d\TH:i:s\Z', time() - 7 * 86400),
                'regionCode' => $settings['region'], 'q' => $term, 'key' => $config['youtube_key']
            ]);
            foreach ($response['items'] ?? [] as $item) if (!empty($item['id']['videoId'])) $ids[$item['id']['videoId']] = true;
        } catch (RadarHttpException $error) { throw $error; }
        catch (Throwable $error) { $errors[] = "$term: {$error->getMessage()}"; }
    }
    if (!$ids) throw new RuntimeException($errors ? implode('; ', $errors) : 'По текущему запросу видео не найдены');
    $videos = [];
    foreach (array_chunk(array_keys($ids), 50) as $batch) {
        $response = radar_youtube_request('videos', ['part' => 'snippet,statistics,contentDetails', 'id' => implode(',', $batch), 'key' => $config['youtube_key']]);
        array_push($videos, ...($response['items'] ?? []));
    }
    $items = array_map(fn($video) => radar_video_item($video), array_values(array_filter($videos, fn($video) => radar_is_relevant($video, $query, (string) $settings['region']))));
    if (!$items) throw new RuntimeException('По выбранным темам пока нет релевантных видео; прежние записи сохранены');
    return [$items, $errors];
}

function radar_fetch_global(array $config): array {
    $response = radar_youtube_request('search', [
        'part' => 'snippet', 'type' => 'video', 'videoDuration' => 'short', 'order' => 'viewCount',
        'maxResults' => 50, 'publishedAfter' => gmdate('Y-m-d\TH:i:s\Z', time() - 7 * 86400),
        'safeSearch' => 'moderate', 'q' => '#shorts', 'key' => $config['youtube_key']
    ]);
    $ids = [];
    foreach ($response['items'] ?? [] as $item) if (!empty($item['id']['videoId'])) $ids[$item['id']['videoId']] = true;
    if (!$ids) throw new RuntimeException('Глобальный поиск не вернул коротких видео');
    $details = radar_youtube_request('videos', ['part' => 'snippet,statistics,contentDetails', 'id' => implode(',', array_keys($ids)), 'key' => $config['youtube_key']]);
    $items = array_map(fn($video) => radar_video_item($video, true), $details['items'] ?? []);
    if (!$items) throw new RuntimeException('Глобальный поиск не вернул видео с метриками; прежние записи сохранены');
    usort($items, fn($a, $b) => $b['views'] <=> $a['views']);
    return $items;
}

function radar_collect(array $config, bool $manual = false): array {
    if (empty($config['youtube_key'])) throw new RadarHttpException('Ключ YouTube API не настроен', 503);
    $dir = dirname(radar_data_file());
    if (!is_dir($dir) && !mkdir($dir, 0700, true) && !is_dir($dir)) throw new RuntimeException('Не удалось создать каталог данных');
    $lock = fopen($dir . '/.sync.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RadarHttpException('Обновление уже идёт', 409);
    try {
        $state = radar_read_state();
        if (!empty($state['youtubeBlockedUntil']) && radar_ms((string) $state['youtubeBlockedUntil']) > time() * 1000) throw new RadarHttpException('Лимит YouTube API достигнут. Повторите позже.', 429);
        if ($manual) {
            $last = radar_ms((string) ($state['lastManualSyncAt'] ?? ''));
            if ($last + 3600000 > time() * 1000) throw new RadarHttpException('Ручное обновление доступно раз в 60 минут', 429);
            radar_update_state(function (array &$saved): void { $saved['lastManualSyncAt'] = radar_now(); });
        }
        $thematicDue = $manual || radar_ms((string) ($state['lastSync'] ?? '')) + 86400000 <= time() * 1000;
        $globalDue = $manual || radar_ms((string) ($state['globalLastSync'] ?? '')) + 86400000 <= time() * 1000;
        $added = 0; $globalAdded = 0; $errors = [];
        if ($thematicDue) {
            try {
                [$items, $partial] = radar_fetch_thematic($config, $state['settings']);
                $added = count($items);
                radar_update_state(function (array &$saved) use ($items, $partial): void {
                    $other = array_values(array_filter($saved['items'], fn($item) => ($item['source'] ?? '') !== 'youtube'));
                    $saved['items'] = array_merge($other, $items);
                    $saved['lastSync'] = radar_now(); $saved['lastUpdated'] = $saved['lastSync'];
                    $saved['syncError'] = $partial ? 'Часть запросов не выполнена: ' . implode('; ', $partial) : null;
                });
            } catch (Throwable $error) {
                $errors[] = 'Темы: ' . $error->getMessage();
                radar_update_state(function (array &$saved) use ($error): void { $saved['syncError'] = $error->getMessage(); });
            }
        }
        if ($globalDue && !(radar_ms((string) (radar_read_state()['youtubeBlockedUntil'] ?? '')) > time() * 1000)) {
            try {
                $items = radar_fetch_global($config); $globalAdded = count($items);
                radar_update_state(function (array &$saved) use ($items): void {
                    $saved['globalItems'] = $items; $saved['globalLastSync'] = radar_now(); $saved['globalSyncError'] = null;
                });
            } catch (Throwable $error) {
                $errors[] = 'Глобально: ' . $error->getMessage();
                radar_update_state(function (array &$saved) use ($error): void { $saved['globalSyncError'] = $error->getMessage(); });
            }
        }
        return ['added' => $added, 'globalAdded' => $globalAdded] + ($errors ? ['warning' => implode('; ', $errors)] : []);
    } finally {
        flock($lock, LOCK_UN); fclose($lock);
    }
}
