import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API 서버 설정
// Android 에뮬레이터: '10.0.2.2:8000'
// iOS 시뮬레이터 / 웹: 'localhost:8000'
// 실제 디바이스: '<서버 IP>:8000'
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
const String kApiBaseUrl = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 컬러 팔레트 (터미널 / 해커 감성)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TermColors {
  static const bg = Color(0xFF0A0E14);
  static const bgCard = Color(0xFF111820);
  static const bgInput = Color(0xFF151C26);
  static const green = Color(0xFF00FF41);
  static const greenDim = Color(0xFF00C234);
  static const cyan = Color(0xFF00D4FF);
  static const yellow = Color(0xFFFFD600);
  static const red = Color(0xFFFF4444);
  static const orange = Color(0xFFFF9800);
  static const textMuted = Color(0xFF4A5568);
  static const textDim = Color(0xFF718096);
  static const border = Color(0xFF1E2A38);
  static const white = Color(0xFFE2E8F0);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 앱 진입점
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
    ),
  );
  runApp(const StockPredictorApp());
}

class StockPredictorApp extends StatelessWidget {
  const StockPredictorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Stock Predictor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: TermColors.bg,
        textTheme: GoogleFonts.jetBrainsMonoTextTheme(
          ThemeData.dark().textTheme,
        ),
      ),
      home: const PredictionScreen(),
    );
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 예측 결과 모델
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class PredictionResult {
  final String ticker;
  final String? stockName;
  final String targetDate;
  final String predictedTrend;
  final int predictedPrice;
  final double trendProbability;
  final double avgSentimentScore;
  final Map<String, dynamic> modelMetrics;

  PredictionResult({
    required this.ticker,
    this.stockName,
    required this.targetDate,
    required this.predictedTrend,
    required this.predictedPrice,
    required this.trendProbability,
    required this.avgSentimentScore,
    required this.modelMetrics,
  });

  factory PredictionResult.fromJson(Map<String, dynamic> json) {
    return PredictionResult(
      ticker: json['ticker'] ?? '',
      stockName: json['stock_name'],
      targetDate: json['target_date'] ?? '',
      predictedTrend: json['predicted_trend'] ?? '알 수 없음',
      predictedPrice: (json['predicted_price'] as num?)?.toInt() ?? 0,
      trendProbability:
          (json['trend_probability'] as num?)?.toDouble() ?? 0.0,
      avgSentimentScore:
          (json['avg_sentiment_score'] as num?)?.toDouble() ?? 0.0,
      modelMetrics:
          (json['model_metrics'] as Map<String, dynamic>?) ?? {},
    );
  }

  bool get isUp => predictedTrend == '상승';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 화면 상태 열거형
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
enum ScreenState { idle, loading, result, error }

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 메인 화면
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class PredictionScreen extends StatefulWidget {
  const PredictionScreen({super.key});

  @override
  State<PredictionScreen> createState() => _PredictionScreenState();
}

class _PredictionScreenState extends State<PredictionScreen>
    with TickerProviderStateMixin {
  final TextEditingController _stockController = TextEditingController();
  final ScrollController _terminalScrollController = ScrollController();

  ScreenState _state = ScreenState.idle;
  PredictionResult? _result;
  String _errorMessage = '';
  bool _serverHealthy = false;

  // ── 터미널 타이핑 애니메이션 ──
  final List<String> _terminalLines = [];
  Timer? _typingTimer;
  int _currentLineIndex = 0;
  int _currentCharIndex = 0;
  String _currentTypingLine = '';

  // ── 커서 깜빡임 ──
  late AnimationController _cursorController;

  // ── 결과 등장 애니메이션 ──
  late AnimationController _resultAnimController;
  late Animation<double> _resultFadeIn;
  late Animation<Offset> _resultSlideUp;

  // 터미널 로딩 메시지 (단계별)
  static const _loadingMessages = [
    '> stock_predictor.py --stock "\${stock}" --year 2024',
    '',
    '[Step 1/6] 종목 정보 조회 중...',
    '  ✓ ticker resolved → \${ticker}',
    '',
    '[Step 2/6] yfinance 주가 데이터 수집 중...',
    '  ↓ downloading OHLCV data...',
    '  ✓ 245 거래일 수집 완료',
    '',
    '[Step 3/6] 네이버 뉴스 크롤링 중...',
    '  ↓ crawling search.naver.com ...',
    '  ↓ month 01/12 ... 03/12 ... 06/12 ...',
    '  ✓ 482건 뉴스 수집 완료',
    '',
    '[Step 4/6] KR-FinBert-SC 감성 분석 중...',
    '  ↓ loading snunlp/KR-FinBert-SC ...',
    '  ↓ analyzing 482 articles in batches ...',
    '  ✓ 감성 분석 완료 (avg: 0.12)',
    '',
    '[Step 5/6] XGBoost 모델 학습 중...',
    '  ↓ preprocessing: MA, RSI, MACD, Bollinger ...',
    '  ↓ training XGBRegressor (200 trees) ...',
    '  ↓ training XGBClassifier ...',
    '  ✓ 모델 저장: models/\${ticker}_regressor.pkl',
    '',
    '[Step 6/6] 다음 거래일 예측 수행 중...',
    '  ↓ loading model & scaler ...',
    '  ↓ inference ...',
    '',
  ];

  @override
  void initState() {
    super.initState();

    _cursorController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true);

    _resultAnimController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _resultFadeIn = CurvedAnimation(
      parent: _resultAnimController,
      curve: Curves.easeOutCubic,
    );
    _resultSlideUp = Tween<Offset>(
      begin: const Offset(0, 0.15),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _resultAnimController,
      curve: Curves.easeOutCubic,
    ));

    _checkServerHealth();
  }

  @override
  void dispose() {
    _typingTimer?.cancel();
    _cursorController.dispose();
    _resultAnimController.dispose();
    _stockController.dispose();
    _terminalScrollController.dispose();
    super.dispose();
  }

  // ── 서버 헬스체크 ──
  Future<void> _checkServerHealth() async {
    try {
      final resp = await http
          .get(Uri.parse('$kApiBaseUrl/health'))
          .timeout(const Duration(seconds: 5));
      setState(() => _serverHealthy = resp.statusCode == 200);
    } catch (_) {
      setState(() => _serverHealthy = false);
    }
  }

  // ── 예측 요청 ──
  Future<void> _requestPrediction() async {
    final stock = _stockController.text.trim();
    if (stock.isEmpty) return;

    setState(() {
      _state = ScreenState.loading;
      _terminalLines.clear();
      _currentLineIndex = 0;
      _currentCharIndex = 0;
      _currentTypingLine = '';
      _result = null;
      _errorMessage = '';
    });

    // 터미널 타이핑 시작
    _startTerminalTyping(stock);

    try {
      final uri = Uri.parse('$kApiBaseUrl/predict').replace(
        queryParameters: {'stock': stock},
      );

      final response = await http.get(uri).timeout(
            const Duration(minutes: 15),
          );

      _typingTimer?.cancel();

      if (response.statusCode == 200) {
        final json = jsonDecode(utf8.decode(response.bodyBytes));
        final result = PredictionResult.fromJson(json);

        // 완료 메시지 추가
        _addTerminalLineInstant('');
        _addTerminalLineInstant(
          '══════════════════════════════════════',
        );
        _addTerminalLineInstant('  ✅ 예측 완료!');
        _addTerminalLineInstant(
          '══════════════════════════════════════',
        );

        await Future.delayed(const Duration(milliseconds: 800));

        setState(() {
          _state = ScreenState.result;
          _result = result;
        });
        _resultAnimController.forward(from: 0);
      } else {
        final body = jsonDecode(utf8.decode(response.bodyBytes));
        throw Exception(body['detail'] ?? 'HTTP ${response.statusCode}');
      }
    } on TimeoutException {
      _typingTimer?.cancel();
      setState(() {
        _state = ScreenState.error;
        _errorMessage = '요청 시간이 초과되었습니다.\n서버 상태를 확인해주세요.';
      });
    } on http.ClientException catch (e) {
      _typingTimer?.cancel();
      setState(() {
        _state = ScreenState.error;
        _errorMessage =
            '서버에 연결할 수 없습니다.\n\n'
            'FastAPI 서버가 실행 중인지 확인해주세요:\n'
            'python3 main.py\n\n'
            '에러: $e';
      });
    } catch (e) {
      _typingTimer?.cancel();
      setState(() {
        _state = ScreenState.error;
        _errorMessage = '$e';
      });
    }
  }

  // ── 터미널 타이핑 애니메이션 ──
  void _startTerminalTyping(String stock) {
    // 템플릿 치환
    final messages = _loadingMessages.map((msg) {
      return msg
          .replaceAll('\${stock}', stock)
          .replaceAll('\${ticker}', '${stock}.KS');
    }).toList();

    _typingTimer = Timer.periodic(
      const Duration(milliseconds: 25),
      (timer) {
        if (_currentLineIndex >= messages.length) {
          // 모든 메시지 타이핑 완료 → 대기 애니메이션
          _showWaitingDots();
          timer.cancel();
          return;
        }

        final currentLine = messages[_currentLineIndex];

        if (currentLine.isEmpty) {
          // 빈 줄은 즉시 추가
          setState(() {
            _terminalLines.add('');
            _currentLineIndex++;
            _currentCharIndex = 0;
            _currentTypingLine = '';
          });
          _scrollTerminalToBottom();
          return;
        }

        if (_currentCharIndex < currentLine.length) {
          setState(() {
            _currentTypingLine += currentLine[_currentCharIndex];
            _currentCharIndex++;
          });
        } else {
          // 한 줄 완성
          setState(() {
            _terminalLines.add(_currentTypingLine);
            _currentLineIndex++;
            _currentCharIndex = 0;
            _currentTypingLine = '';
          });
          _scrollTerminalToBottom();
        }
      },
    );
  }

  // 서버 응답 대기 중 점 애니메이션
  void _showWaitingDots() {
    int dotCount = 0;
    _typingTimer = Timer.periodic(
      const Duration(milliseconds: 500),
      (timer) {
        dotCount = (dotCount % 3) + 1;
        setState(() {
          _currentTypingLine = '  ⏳ 서버 응답 대기 중${'.' * dotCount}';
        });
      },
    );
  }

  void _addTerminalLineInstant(String line) {
    setState(() {
      _terminalLines.add(line);
      _currentTypingLine = '';
    });
    _scrollTerminalToBottom();
  }

  void _scrollTerminalToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_terminalScrollController.hasClients) {
        _terminalScrollController.animateTo(
          _terminalScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 100),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ── 화면 초기화 (새 검색) ──
  void _resetToIdle() {
    _typingTimer?.cancel();
    setState(() {
      _state = ScreenState.idle;
      _result = null;
      _errorMessage = '';
      _terminalLines.clear();
      _currentTypingLine = '';
    });
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // 빌드
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(),
            Expanded(child: _buildBody()),
          ],
        ),
      ),
    );
  }

  // ── 헤더 ──
  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      decoration: const BoxDecoration(
        border: Border(
          bottom: BorderSide(color: TermColors.border, width: 1),
        ),
      ),
      child: Row(
        children: [
          // 로고
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              color: _serverHealthy ? TermColors.green : TermColors.red,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: (_serverHealthy ? TermColors.green : TermColors.red)
                      .withOpacity(0.5),
                  blurRadius: 8,
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            'STOCK_PREDICTOR',
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.green,
              fontSize: 16,
              fontWeight: FontWeight.bold,
              letterSpacing: 2,
            ),
          ),
          const Spacer(),
          // 서버 상태
          Text(
            _serverHealthy ? 'SERVER ONLINE' : 'SERVER OFFLINE',
            style: GoogleFonts.jetBrainsMono(
              color: _serverHealthy ? TermColors.greenDim : TermColors.red,
              fontSize: 10,
              letterSpacing: 1,
            ),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: _checkServerHealth,
            child: Icon(
              Icons.refresh,
              color: TermColors.textMuted,
              size: 16,
            ),
          ),
        ],
      ),
    );
  }

  // ── 본문 (상태에 따라 전환) ──
  Widget _buildBody() {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 400),
      child: switch (_state) {
        ScreenState.idle => _buildIdleView(),
        ScreenState.loading => _buildLoadingView(),
        ScreenState.result => _buildResultView(),
        ScreenState.error => _buildErrorView(),
      },
    );
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // IDLE: 검색 화면
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Widget _buildIdleView() {
    return SingleChildScrollView(
      key: const ValueKey('idle'),
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 40),
          // ASCII Art 타이틀
          Center(
            child: Text(
              '╔══════════════════════════════╗\n'
              '║   AI STOCK PREDICTOR v1.0    ║\n'
              '║   Powered by XGBoost + NLP   ║\n'
              '╚══════════════════════════════╝',
              style: GoogleFonts.jetBrainsMono(
                color: TermColors.cyan,
                fontSize: 13,
                height: 1.5,
              ),
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 48),

          // 프롬프트
          Text(
            'Enter stock name or ticker:',
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.textDim,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 12),

          // 입력 필드
          Container(
            decoration: BoxDecoration(
              color: TermColors.bgInput,
              border: Border.all(color: TermColors.green.withOpacity(0.3)),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Padding(
                  padding: const EdgeInsets.only(left: 16),
                  child: Text(
                    '\$',
                    style: GoogleFonts.jetBrainsMono(
                      color: TermColors.green,
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                Expanded(
                  child: TextField(
                    controller: _stockController,
                    style: GoogleFonts.jetBrainsMono(
                      color: TermColors.white,
                      fontSize: 16,
                    ),
                    decoration: InputDecoration(
                      hintText: '삼성전자',
                      hintStyle: GoogleFonts.jetBrainsMono(
                        color: TermColors.textMuted,
                        fontSize: 16,
                      ),
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 16,
                      ),
                    ),
                    onSubmitted: (_) => _requestPrediction(),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // 실행 버튼
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: _serverHealthy ? _requestPrediction : null,
              style: ElevatedButton.styleFrom(
                backgroundColor: TermColors.green.withOpacity(0.15),
                foregroundColor: TermColors.green,
                side: BorderSide(
                  color: TermColors.green.withOpacity(0.4),
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              child: Text(
                _serverHealthy
                    ? '▶  RUN PREDICTION'
                    : '⚠  SERVER OFFLINE',
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                ),
              ),
            ),
          ),
          const SizedBox(height: 32),

          // 안내 텍스트
          _infoRow('💡', '종목명(삼성전자) 또는 코드(005930) 입력'),
          const SizedBox(height: 8),
          _infoRow('⏱️', '최초 실행 시 3~5분 소요 (크롤링+학습)'),
          const SizedBox(height: 8),
          _infoRow('🌐', '서버: $kApiBaseUrl'),
        ],
      ),
    );
  }

  Widget _infoRow(String icon, String text) {
    return Row(
      children: [
        Text(icon, style: const TextStyle(fontSize: 14)),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            text,
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.textMuted,
              fontSize: 11,
            ),
          ),
        ),
      ],
    );
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // LOADING: 터미널 타이핑 애니메이션
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Widget _buildLoadingView() {
    return Container(
      key: const ValueKey('loading'),
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TermColors.bgCard,
        border: Border.all(color: TermColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 터미널 타이틀 바
          _terminalTitleBar(),
          const SizedBox(height: 12),
          // 터미널 본문
          Expanded(
            child: ListView.builder(
              controller: _terminalScrollController,
              itemCount: _terminalLines.length + 1, // +1 for typing line
              itemBuilder: (context, index) {
                if (index < _terminalLines.length) {
                  return _terminalLineWidget(_terminalLines[index]);
                }
                // 현재 타이핑 중인 줄 + 깜빡이는 커서
                return Row(
                  children: [
                    Flexible(
                      child: Text(
                        _currentTypingLine,
                        style: GoogleFonts.jetBrainsMono(
                          color: _getLineColor(_currentTypingLine),
                          fontSize: 12,
                          height: 1.6,
                        ),
                      ),
                    ),
                    AnimatedBuilder(
                      animation: _cursorController,
                      builder: (_, __) => Opacity(
                        opacity: _cursorController.value,
                        child: Text(
                          '█',
                          style: GoogleFonts.jetBrainsMono(
                            color: TermColors.green,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _terminalTitleBar() {
    return Row(
      children: [
        _dot(TermColors.red),
        const SizedBox(width: 6),
        _dot(TermColors.yellow),
        const SizedBox(width: 6),
        _dot(TermColors.green),
        const SizedBox(width: 16),
        Expanded(
          child: Text(
            'stock_predictor — running',
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.textMuted,
              fontSize: 11,
            ),
          ),
        ),
        GestureDetector(
          onTap: _resetToIdle,
          child: Text(
            '[CANCEL]',
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.red.withOpacity(0.7),
              fontSize: 10,
              letterSpacing: 1,
            ),
          ),
        ),
      ],
    );
  }

  Widget _dot(Color color) {
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }

  Widget _terminalLineWidget(String line) {
    return Text(
      line,
      style: GoogleFonts.jetBrainsMono(
        color: _getLineColor(line),
        fontSize: 12,
        height: 1.6,
      ),
    );
  }

  Color _getLineColor(String line) {
    if (line.startsWith('>')) return TermColors.white;
    if (line.startsWith('[Step')) return TermColors.cyan;
    if (line.contains('✓')) return TermColors.green;
    if (line.contains('✅')) return TermColors.green;
    if (line.contains('↓')) return TermColors.yellow;
    if (line.contains('⏳')) return TermColors.orange;
    if (line.contains('═')) return TermColors.cyan;
    return TermColors.textDim;
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // RESULT: 대시보드
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Widget _buildResultView() {
    final r = _result!;
    final priceFormat = NumberFormat('#,###');
    final isUp = r.isUp;
    final trendColor = isUp ? TermColors.green : TermColors.red;
    final trendIcon = isUp ? '▲' : '▼';

    return SlideTransition(
      position: _resultSlideUp,
      child: FadeTransition(
        opacity: _resultFadeIn,
        child: SingleChildScrollView(
          key: const ValueKey('result'),
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 종목 헤더
              _resultHeader(r),
              const SizedBox(height: 24),

              // ── 예측 종가 (메인 카드) ──
              _glowCard(
                borderColor: trendColor,
                child: Column(
                  children: [
                    Text(
                      '예측 종가',
                      style: GoogleFonts.jetBrainsMono(
                        color: TermColors.textDim,
                        fontSize: 12,
                        letterSpacing: 1,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          trendIcon,
                          style: TextStyle(color: trendColor, fontSize: 28),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          priceFormat.format(r.predictedPrice),
                          style: GoogleFonts.jetBrainsMono(
                            color: trendColor,
                            fontSize: 36,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4, left: 4),
                          child: Text(
                            '원',
                            style: GoogleFonts.jetBrainsMono(
                              color: trendColor.withOpacity(0.6),
                              fontSize: 16,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 4),
                      decoration: BoxDecoration(
                        color: trendColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        '${r.predictedTrend} 예측',
                        style: GoogleFonts.jetBrainsMono(
                          color: trendColor,
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // ── 상승 확률 + 감성 스코어 (2열) ──
              Row(
                children: [
                  Expanded(
                    child: _metricCard(
                      label: '상승 확률',
                      value:
                          '${(r.trendProbability * 100).toStringAsFixed(1)}%',
                      progress: r.trendProbability,
                      color: r.trendProbability >= 0.5
                          ? TermColors.green
                          : TermColors.red,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _metricCard(
                      label: '감성 스코어',
                      value: r.avgSentimentScore.toStringAsFixed(4),
                      progress:
                          (r.avgSentimentScore + 1) / 2, // -1~1 → 0~1
                      color: r.avgSentimentScore >= 0
                          ? TermColors.cyan
                          : TermColors.orange,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              // ── 모델 성능 지표 ──
              _buildModelMetrics(r.modelMetrics),
              const SizedBox(height: 24),

              // ── 새 검색 버튼 ──
              SizedBox(
                width: double.infinity,
                height: 48,
                child: OutlinedButton.icon(
                  onPressed: _resetToIdle,
                  icon: const Icon(Icons.search, size: 18),
                  label: Text(
                    'NEW PREDICTION',
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 13,
                      letterSpacing: 1.5,
                    ),
                  ),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: TermColors.cyan,
                    side: const BorderSide(color: TermColors.cyan),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                ),
              ),

              // ── 면책 조항 ──
              const SizedBox(height: 20),
              Text(
                '⚠ 본 예측은 AI 모델의 학습 결과이며 투자 자문이 아닙니다.\n'
                '   실제 투자 판단 시 반드시 전문가의 조언을 구하세요.',
                style: GoogleFonts.jetBrainsMono(
                  color: TermColors.textMuted,
                  fontSize: 9,
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _resultHeader(PredictionResult r) {
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: TermColors.cyan.withOpacity(0.1),
            border: Border.all(color: TermColors.cyan.withOpacity(0.3)),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            r.ticker,
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.cyan,
              fontSize: 13,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        const SizedBox(width: 10),
        if (r.stockName != null)
          Text(
            r.stockName!,
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.white,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
        const Spacer(),
        Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              '예측일',
              style: GoogleFonts.jetBrainsMono(
                color: TermColors.textMuted,
                fontSize: 9,
              ),
            ),
            Text(
              r.targetDate,
              style: GoogleFonts.jetBrainsMono(
                color: TermColors.textDim,
                fontSize: 12,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _glowCard({required Color borderColor, required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
      decoration: BoxDecoration(
        color: TermColors.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor.withOpacity(0.3)),
        boxShadow: [
          BoxShadow(
            color: borderColor.withOpacity(0.08),
            blurRadius: 24,
            spreadRadius: 0,
          ),
        ],
      ),
      child: child,
    );
  }

  Widget _metricCard({
    required String label,
    required String value,
    required double progress,
    required Color color,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TermColors.bgCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TermColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.textMuted,
              fontSize: 10,
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            value,
            style: GoogleFonts.jetBrainsMono(
              color: color,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          // 프로그레스 바
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: progress.clamp(0.0, 1.0),
              backgroundColor: color.withOpacity(0.1),
              valueColor: AlwaysStoppedAnimation(color),
              minHeight: 4,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildModelMetrics(Map<String, dynamic> metrics) {
    final reg = metrics['regression'] as Map<String, dynamic>? ?? {};
    final clf = metrics['classification'] as Map<String, dynamic>? ?? {};

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TermColors.bgCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TermColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'MODEL PERFORMANCE',
            style: GoogleFonts.jetBrainsMono(
              color: TermColors.textMuted,
              fontSize: 10,
              letterSpacing: 1.5,
            ),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                  child: _metricTile('MAE', '${reg['mae'] ?? 'N/A'}',
                      TermColors.yellow)),
              Expanded(
                  child: _metricTile('RMSE', '${reg['rmse'] ?? 'N/A'}',
                      TermColors.orange)),
              Expanded(
                  child: _metricTile(
                      'Accuracy',
                      '${clf['accuracy'] ?? 'N/A'}',
                      TermColors.cyan)),
              Expanded(
                  child: _metricTile(
                      'F1', '${clf['f1'] ?? 'N/A'}', TermColors.green)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _metricTile(String label, String value, Color color) {
    return Column(
      children: [
        Text(
          value,
          style: GoogleFonts.jetBrainsMono(
            color: color,
            fontSize: 14,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: GoogleFonts.jetBrainsMono(
            color: TermColors.textMuted,
            fontSize: 9,
          ),
        ),
      ],
    );
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // ERROR: 에러 화면
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Widget _buildErrorView() {
    return Center(
      key: const ValueKey('error'),
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: TermColors.red.withOpacity(0.08),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.error_outline,
                color: TermColors.red,
                size: 48,
              ),
            ),
            const SizedBox(height: 24),
            Text(
              'ERROR',
              style: GoogleFonts.jetBrainsMono(
                color: TermColors.red,
                fontSize: 20,
                fontWeight: FontWeight.bold,
                letterSpacing: 3,
              ),
            ),
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: TermColors.bgCard,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: TermColors.red.withOpacity(0.2)),
              ),
              child: Text(
                _errorMessage,
                style: GoogleFonts.jetBrainsMono(
                  color: TermColors.textDim,
                  fontSize: 12,
                  height: 1.6,
                ),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 32),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                OutlinedButton(
                  onPressed: _resetToIdle,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: TermColors.cyan,
                    side: const BorderSide(color: TermColors.cyan),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 24, vertical: 14),
                  ),
                  child: Text(
                    '← BACK',
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 12,
                      letterSpacing: 1,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: _requestPrediction,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: TermColors.green.withOpacity(0.15),
                    foregroundColor: TermColors.green,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 24, vertical: 14),
                  ),
                  child: Text(
                    'RETRY ↻',
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 12,
                      letterSpacing: 1,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
