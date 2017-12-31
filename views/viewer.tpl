<script>
var selectpage = document.getElementById('select-page');
var currentpage = document.getElementById('currentPage');

selectpage.value = (currentpage && currentpage.value) ? currentpage.value : 1;

var viewer = OpenSeadragon({
  id: "dzi",
  showRotationControl: false,
  minZoomImageRatio: 0.5,
  maxZoomImageRatio: 2.0,
  showFullPageControl: false,
  degrees: 0,
  showHomeControl: false,
  sequenceMode: true,
  initialPage: currentpage ? currentpage.value : 0,
  prefixUrl: "/static/images/",
  tileSources: [
  % for n in range(1, project.source['pages']):
    "{{project.source['dzi']}}{{n}}.dzi.dzi",
  % end
  ]
});

var ancient = this.viewer.fabricjsOverlay({ scale: 1000 });

% if get('browse'):
var overlay = ancient;
% else:
var overlay = this.viewer.fabricjsOverlay({ scale: 1000 });
% end

overlay.fabricCanvas().on("mouse:up", function(options) {
  serialize();
});

function markpage(button) {
  var drawing = overlay.fabricCanvas().isDrawingMode;
  if(drawing) {
    viewer.setMouseNavEnabled(true);
    viewer.outerTracker.setTracking(true);
    overlay.fabricCanvas().isDrawingMode = false;
    button.textContent = "{{_("mark-page")}}";
    serialize();
  } else {
    viewer.setMouseNavEnabled(false);
    viewer.outerTracker.setTracking(false);
    overlay.fabricCanvas().isDrawingMode = true;
    overlay.fabricCanvas().freeDrawingBrush.width = 30;
    overlay.fabricCanvas().freeDrawingBrush.color = "rgba(255, 0, 0, 0.3)";
    button.textContent = "{{_("finish-marking-page")}}";
  }
}

selectpage.onchange = function(e) {
  viewer.goToPage(e.target.value - 1);
  if(currentpage) currentpage.value = e.target.value;
}

viewer.addHandler("page", function(e) {
  overlay.fabricCanvas().clear();
  ancient.fabricCanvas().clear();
  var annotation = document.getElementById("annotation");
  if(annotation && annotation.value) {
    var pages = JSON.parse(annotation.value);
    var cv = overlay.fabricCanvas();
    cv.loadFromJSON(pages[e.page], cv.renderAll.bind(cv), function(o, ob) {
      ob.stroke = "rgba(255, 0, 0, 0.3)";
    });
  }
  if(selectpage) {
    selectpage.value = e.page + 1;
  }
  if(currentpage) currentpage.value = e.page;

  % if not get('id'):
  T.getmarkings(e.page, ancient.fabricCanvas());
  % end
});

var pages = {};
var serialize = function(e) {
  console.log("lagrer");
  var json = overlay.fabricCanvas().toJSON()
  var annotation = document.getElementById("annotation");
  var page = viewer.currentPage();
  pages[page] = json;
  if(annotation) {
    annotation.value = JSON.stringify(pages);
  }
  var overview = document.getElementById("marked-pages");
  if(overview) {
    var marked = Object.keys(pages).join(", ");
    overview.value = marked;
  }
}
% if not get('id'):
var p = (currentpage && currentpage.value) ? currentpage.value : 0;
T.getmarkings(p, ancient.fabricCanvas());
% else:
viewer.raiseEvent("page", { page: viewer.currentPage() });
% end
</script>
